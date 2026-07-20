"""Lifecycle mixin for BaseModel: external IDs, archive/unarchive, registration
hooks, onchange support, and model identity/URL helpers.
"""

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
    """Mixin providing lifecycle and metadata operations for recordsets."""

    __slots__ = ()

    def _get_external_ids(self) -> dict[IdType, list[str]]:
        """Retrieve the External ID(s) of any database record.

        :return: map of ids to the list of their fully qualified External IDs
                 in the form ``module.key``, or an empty list when there's no
                 External ID for a record, e.g.::

                     {"id": ["module.ext_id", "module.ext_id_bis"], "id2": []}
        """
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
        """Retrieve one External ID per record (chosen arbitrarily when several
        exist). Usable as a function field via ``Model.get_external_id``.

        :return: map of ids to their fully qualified XML ID, defaulting to an
                 empty string when there's none, e.g.::

                     {"id": "module.ext_id", "id2": ""}
        """
        results = self._get_external_ids()
        return {key: val[0] if val else "" for key, val in results.items()}

    @classmethod
    def is_transient(cls) -> bool:
        """Return whether the model is transient.

        See :class:`TransientModel`.

        """
        return cls._transient

    @api.deprecated("Deprecated since 19.0, use action_archive or action_unarchive")
    def toggle_active(self) -> None:
        "Inverses the value of :attr:`active` on the records in ``self``."
        if not self._active_name:
            # raise (not assert) so misconfiguration surfaces under python -O
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        active_recs = self.filtered(self._active_name)
        active_recs.action_archive()
        (self - active_recs).action_unarchive()

    def action_archive(self) -> None:
        """Set :attr:`active` to ``False`` on a recordset for active records.

        Note, you probably want to override `write()` method if you want to take
        action once the active field changes.
        """
        field_name = self._active_name
        if not field_name:
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        active_recs = self.filtered(lambda record: record[field_name])
        active_recs[field_name] = False

    def action_unarchive(self) -> None:
        """Set :attr:`active` to ``True`` on a recordset for inactive records.

        Note, you probably want to override `write()` method if you want to take
        action once the active field changes.
        """
        field_name = self._active_name
        if not field_name:
            raise UserError(self.env._("No 'active' field on model %s", self._name))
        inactive_recs = self.filtered(lambda record: not record[field_name])
        inactive_recs[field_name] = True

    def _register_hook(self) -> None:
        """Run right after the registry is built (override point)."""

    def _unregister_hook(self) -> None:
        """Clean up what :meth:`_register_hook` has done."""

    def _get_redirect_suggested_company(self) -> typing.Any:
        """Return the company to set on the context when redirecting to this
        record via a shared link, to avoid multi-company issues. Override to
        pick a better-suited company (e.g. hr.leave uses the leave type's
        company, per its ir.rule).
        """
        if "company_id" in self:
            return self.company_id
        elif "company_ids" in self:
            return (self.company_ids & self.env.user.company_ids)[:1]
        return False

    def _can_return_content(
        self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        """Determine whether one can export a file or an image from a field of
        record ``self``, even if ``self`` is not accessible to the current user.
        If so, the record will be ``sudo()``-ed to access the corresponding file
        or image.

        :param field_name: image field name to check the access to
        :param access_token: access token to use instead of the
            access rights and access rules
        :return: whether the extra access is allowed
        """
        self.ensure_one()
        return False

    #
    # Generic onchange method
    #

    def _has_onchange(self, field: Field, other_fields: Collection[Field]) -> bool:
        """Return whether ``field`` should trigger an onchange event in the
        presence of ``other_fields``.
        """
        return (field.name in self._onchange_methods) or any(
            dep in other_fields
            for dep in self.pool.get_dependent_fields(field.base_field)
        )

    def _apply_onchange_methods(
        self, field_name: str, result: dict, excluded_methods=()
    ) -> None:
        """Apply onchange method(s) (not in ``excluded_methods``) for field
        ``field_name`` on ``self``. Value assignments are applied on ``self``,
        while warning messages are put in dictionary ``result``.
        """
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
        """Returns the filename of the placeholder to use,
        set on web/static/img by default, or the
        complete path to access it (eg: module/path/to/image.png).
        """
        return False
