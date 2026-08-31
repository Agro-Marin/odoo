from __future__ import annotations

import typing

from ...fields.base import determine
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field


class _FieldComputeMixin(_ModelStubs):
    __slots__ = ()

    def _compute_field_value(self, field: Field, validate: bool = True) -> None:
        determine(field.compute, self)

        if validate:
            self._check_computed(field)

    def _check_computed(self, field: Field) -> None:
        if field.store and any(self._ids):
            fnames = [f.name for f in self.pool.field_computed[field]]
            self.filtered("id")._check_fields(fnames)
