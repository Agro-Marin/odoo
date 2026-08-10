from __future__ import annotations

import functools
import typing

from ._field_stubs import _FieldStubs

if typing.TYPE_CHECKING:
    from .._typing import BaseModel
    from ..runtime import Environment


class _FieldMetadataMixin(_FieldStubs):
    __slots__ = ()

    name: str = ""
    model_name: str = ""

    store: bool = True
    translate: bool = False
    company_dependent: bool = False

    _column_type: tuple[str, str] | None = None

    @functools.cached_property
    def column_type(self) -> tuple[str, str] | None:
        return (
            ("jsonb", "jsonb")
            if self.company_dependent or self.translate
            else self._column_type
        )

    @functools.cached_property
    def is_column(self) -> bool:
        return bool(self.store and self.column_type)

    def _is_context_dependent(self, env: Environment) -> bool:
        return self in env._field_depends_context

    def _company_dependent_fallback_raw(self, records: BaseModel) -> typing.Any:
        return records.env._ir_defaults._get_model_defaults(records._name).get(
            self.name
        )
