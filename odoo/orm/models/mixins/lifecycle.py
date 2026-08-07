import typing
from collections import defaultdict

from odoo.exceptions import UserError
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import (
    DomainType,
    IdType,
)
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Collection

    from ...fields.base import Field


class LifecycleMixin(_ModelStubs):
    __slots__ = ()

    def _get_external_ids(self) -> dict[IdType, list[str]]:
        result = defaultdict(list)
        domain: DomainType = [
            ("model", "=", self._name),
            ("res_id", "in", self.ids),
        ]
        for data in (
            self.env["ir.model.data"]
            .sudo()
            .search_read(domain, ["module", "name", "res_id"], order="id")
        ):
            result[data["res_id"]].append(f"{data['module']}.{data['name']}")
        return {record.id: result[record._origin.id] for record in self}

    def get_external_id(self) -> dict[IdType, str]:
        results = self._get_external_ids()
        return {key: val[0] if val else "" for key, val in results.items()}

    @classmethod
    def is_transient(cls) -> bool:
        return cls._transient

    @api.deprecated("Deprecated since 19.0, use action_archive or action_unarchive")
    def toggle_active(self) -> None:
        if not self._active_name:
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        active_recs = self.filtered(self._active_name)
        active_recs.action_archive()
        (self - active_recs).action_unarchive()

    def action_archive(self) -> None:
        field_name = self._active_name
        if not field_name:
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        active_recs = self.filtered(lambda record: record[field_name])
        active_recs[field_name] = False

    def action_unarchive(self) -> None:
        field_name = self._active_name
        if not field_name:
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        inactive_recs = self.filtered(lambda record: not record[field_name])
        inactive_recs[field_name] = True

    def _register_hook(self) -> None:
        pass

    def _unregister_hook(self) -> None:
        pass

    def _get_redirect_suggested_company(self) -> typing.Any:
        if "company_id" in self:
            return self.company_id
        elif "company_ids" in self:
            return (self.company_ids & self.env.user.company_ids)[:1]
        return False

    def _can_return_content(
        self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        self.ensure_one()
        return False

    def _has_onchange(self, field: Field, other_fields: Collection[Field]) -> bool:
        return (field.name in self._onchange_methods) or any(
            dep in other_fields
            for dep in self.pool.get_dependent_fields(field.base_field)
        )

    def _apply_onchange_methods(
        self, field_name: str, result: dict, excluded_methods=()
    ) -> None:
        for method in self._onchange_methods.get(field_name, ()):
            if method in excluded_methods:
                continue
            res = method(self)
            if not res:
                continue
            if res.get("value"):
                for key, val in res["value"].items():
                    if key in self._fields and key != "id":
                        self[key] = val
            if res.get("warning"):
                result["warnings"].add(
                    (
                        res["warning"].get("title") or _("Warning"),
                        res["warning"].get("message") or "",
                        res["warning"].get("type") or "",
                    )
                )

    def onchange(self, values: dict, field_names: list[str], fields_spec: dict) -> dict:
        msg = "onchange() is implemented in module 'web'"
        raise NotImplementedError(msg)

    def _get_placeholder_filename(self, field: str) -> str | bool:
        return False
