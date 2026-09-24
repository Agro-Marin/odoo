from __future__ import annotations

import typing
from functools import partial

from odoo.libs.debug_log import DebugLog

from ...fields.base import call_hook
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field

_debug = DebugLog(__name__)


class _FieldComputeMixin(_ModelStubs):
    __slots__ = ()

    def _compute_field_value(self, field: Field, validate: bool = True) -> None:
        if _debug.perf.enabled:
            with _debug.perf(
                "compute.field",
                cr=getattr(self.env, "cr", None),
                model=field.model_name,
                field=field.name,
                records=len(self),
                validate=validate,
            ):
                call_hook(field.compute, self)
        else:
            call_hook(field.compute, self)

        if validate:
            self._check_computed(field)

    def _check_computed(self, field: Field) -> None:
        if field.store and any(self._ids):
            fnames = [f.name for f in self.pool.field_computed[field]]
            if _debug.pipeline.enabled:
                _debug.pipeline(
                    "compute.checked",
                    model=field.model_name,
                    field=field.name,
                    records=len(self),
                    fields=len(fnames),
                )
            records = self.filtered("id")
            core = self.env.core
            if core.protection_depth():
                if _debug.pipeline.enabled:
                    _debug.pipeline(
                        "compute.check_deferred",
                        model=field.model_name,
                        field=field.name,
                        records=len(records),
                    )
                core.defer_until_unprotected(
                    partial(records._check_fields_if_they_exist, fnames)
                )
            else:
                records._check_fields(fnames)

    def _check_fields_if_they_exist(self, fnames: list[str]) -> None:
        deleted = self.env.core.deleted_ids(self._name)
        if deleted is None:
            records = self.exists()
        elif deleted:
            records = self.browse([id_ for id_ in self._ids if id_ not in deleted])
        else:
            records = self
        if _debug.logic.enabled and len(records) != len(self):
            _debug.logic(
                "compute.deferred_check_skipped_deleted",
                model=self._name,
                fields=fnames,
                deleted=len(self) - len(records),
            )
        if records:
            records._check_fields(fnames)
