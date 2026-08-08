from __future__ import annotations

import functools
import typing

from ._field_stubs import _FieldStubs

if typing.TYPE_CHECKING:
    from .._typing import BaseModel
    from ..runtime import Environment


class _FieldMetadataMixin(_FieldStubs):
    """What a field *is*, as a column — the declarations and what derives from them.

    A leaf: nothing here reaches any other unit of the ``Field`` composition, so
    nothing it is used by can close a cycle through it.

    That is the point of extracting it. When ``mixin_coupling_check`` was
    generalised to measure ``Field`` (it had only ever measured ``BaseModel``),
    its first run found a 2-cycle: ``base.py`` reached ``_field_convert`` from
    the descriptor protocol (``convert_to_cache`` / ``convert_to_record`` /
    ``convert_to_write``) while ``_field_convert`` reached back into ``base.py``
    for exactly these members — ``column_type``, ``company_dependent``,
    ``translate``, ``_is_context_dependent``, ``_company_dependent_fallback_raw``.
    Conversion needs to know a field's *shape*, not the composition root.

    This is the same fix ``models/`` already made, and for the same reason:
    ``base.py`` was the articulation point of a nine-unit cycle until its model
    metadata moved onto ``_metadata`` / ``_properties`` / ``_magic_fields``
    leaves. A composition root that holds the declarations every other unit
    reads is a hub, whatever it is called.

    Scope is deliberately "the column shape", not "every declared attribute".
    ``Field`` declares around forty; the ones here are those that answer *what
    column does this field become, and under what key is it cached* — which is
    the question conversion, SQL generation and description all ask, and the
    only cluster whose removal breaks the cycle. Widening it further would be a
    separate, larger move with no gate movement to show for it.
    """

    __slots__ = ()

    #: Set by ``__set_name__`` / ``_setup_attrs__`` through
    #: ``self.__dict__.update(attrs)``, so the instance attribute shadows these
    #: class-level defaults. Declaring them on a base rather than on ``Field``
    #: changes neither lookup nor ``hasattr``, which ``_get_attrs`` relies on to
    #: compute ``_extra_keys__``.
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
