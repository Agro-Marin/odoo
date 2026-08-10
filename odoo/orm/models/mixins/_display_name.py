from __future__ import annotations

from odoo.exceptions import UserError

from ... import decorators as api
from ._model_stubs import _ModelStubs


class _DisplayNameMixin(_ModelStubs):
    __slots__ = ()

    @api.model
    def _rec_name_fallback(self) -> str:
        return self._rec_name or "id"

    @api.depends(
        lambda self: (
            (self._rec_name,) if self._rec_name and self._rec_name != "id" else ()
        )
    )
    def _compute_display_name(self) -> None:
        if self._rec_name:
            convert = self._fields[self._rec_name].convert_to_display_name
            for record in self:
                record.display_name = convert(record[self._rec_name], record)
        else:
            for record in self:
                record.display_name = f"{record._name},{record.id}"

    @api.model
    def name_create(self, name: str) -> tuple[int, str]:
        if not self._rec_name:
            raise UserError(
                f"Cannot execute name_create: no _rec_name defined on {self._name}"
            )
        record = self.create({self._rec_name: name})
        return record.id, record.display_name
