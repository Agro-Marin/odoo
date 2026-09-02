import typing
from itertools import batched
from typing import Self

from odoo.libs.profiling import _n1_enabled, _OrmProfile

from ...fields.reference import REFERENCE_VERIFIED_CACHE_KEY, Reference
from ...primitives import MODULE_UNINSTALL_FLAG
from ._crud_common import (
    _orm_crud,
    _unlink,
)
from ._model_stubs import _ModelStubs

_UNLINK_LOG_MAX_IDS = 1000


class UnlinkMixin(_ModelStubs):
    __slots__ = ()

    def unlink(self) -> typing.Literal[True]:
        if not self:
            return True

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("unlink", self._name, len(self), frozenset())

        self.check_access("unlink")
        prof.mark("acl")

        for func in self._ondelete_methods:
            if func._ondelete or not self.env.context.get(MODULE_UNINSTALL_FLAG):
                func(self)
        prof.mark("ondelete")

        self.env.flush_all()
        prof.mark("flush")

        cr = self.env.cr
        Data = self.env["ir.model.data"].sudo().with_context({})
        Defaults = self.env["ir.default"].sudo()
        Attachment = self.env["ir.attachment"].sudo()
        ir_model_data_unlink = Data
        ir_attachment_unlink = Attachment

        with self.env.protecting(self._fields.values(), self):
            self._modified_before(self._fields)

        # after _modified_before, not before it: the trigger walk can mark the
        # very ids being deleted (self-referencing computes), and such marks
        # would later be computed against missing rows
        core = self.env._core
        if core.has_pending():
            model_name = self._name
            pending_ids = self._ids
            for field in core.pending_fields():
                if field.model_name == model_name:
                    core.mark_done(field, pending_ids)
        prof.mark("before")

        deleted_ids: list[int] = self.ids
        for sub_ids in batched(deleted_ids, cr.BATCH_SIZE, strict=False):
            data, attachments = self._unlink_process_batch(
                sub_ids,
                Data,
                Defaults,
                Attachment,
            )
            ir_model_data_unlink |= data
            ir_attachment_unlink |= attachments
        prof.mark("sql")

        if self.env.context.get(MODULE_UNINSTALL_FLAG):
            self.env.invalidate_all(flush=False)
            self.env.cr.cache.pop(REFERENCE_VERIFIED_CACHE_KEY, None)
        else:
            self._invalidate_after_delete()

        if ir_model_data_unlink:
            ir_model_data_unlink.unlink()
        if ir_attachment_unlink:
            ir_attachment_unlink.unlink()

        self._log_unlinked_ids(deleted_ids)

        prof.stop("invalidate")
        self._log_unlink_profile(prof, len(deleted_ids))

        return True

    def _log_unlinked_ids(self, deleted_ids: list[int]) -> None:
        if len(deleted_ids) <= _UNLINK_LOG_MAX_IDS:
            _unlink.info(
                "User #%s deleted %s records with IDs: %r",
                self.env.uid,
                self._name,
                deleted_ids,
            )
        else:
            _unlink.info(
                "User #%s deleted %s records: %d IDs in [%s..%s], first %d: %r",
                self.env.uid,
                self._name,
                len(deleted_ids),
                min(deleted_ids),
                max(deleted_ids),
                _UNLINK_LOG_MAX_IDS,
                deleted_ids[:_UNLINK_LOG_MAX_IDS],
            )

    def _log_unlink_profile(self, prof: _OrmProfile, record_count: int) -> None:
        prof.report(_orm_crud, "unlink %s: %d records", self._name, record_count)
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record("unlink", self._name, record_count, prof.elapsed)

    def _invalidate_after_delete(self) -> None:
        env = self.env
        registry = env.registry
        cascades = registry.models_cascading_from
        gone = {self._name}
        todo = [self._name]
        while todo:
            for model_name in cascades.get(todo.pop(), ()):
                if model_name not in gone:
                    gone.add(model_name)
                    todo.append(model_name)
        fields_by_comodel = registry.fields_by_comodel
        for model_name in gone:
            for field in env[model_name]._fields.values():
                field._invalidate_cache(env, keep_dirty=True)
            for field in fields_by_comodel.get(model_name, ()):
                field._invalidate_cache(env, keep_dirty=True)
        for field in registry.fields_reading_through_a_reference:
            field._invalidate_cache(env, keep_dirty=True)
        Reference.discard_verified_models(env, gone)
        self._forget_ref_cache(gone)

    def _forget_ref_cache(self, model_names: typing.Iterable[str]) -> None:
        ref_cache = self.env.transaction._ref_cache
        if not ref_cache:
            return
        names = set(model_names)
        for key in [key for key in ref_cache if key[0] in names]:
            del ref_cache[key]

    def _unlink_process_batch(
        self,
        sub_ids: tuple[int, ...],
        Data: typing.Any,
        Defaults: typing.Any,
        Attachment: typing.Any,
    ) -> tuple[Self, Self]:
        return self.env.backend.delete(self, sub_ids, Data, Defaults, Attachment)
