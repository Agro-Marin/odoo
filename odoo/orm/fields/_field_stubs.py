"""Typing-only declaration of the shared ``Field`` surface.

``_FieldDescriptionMixin`` / ``_FieldConvertMixin`` / ``_FieldSqlMixin`` are
composed onto :class:`Field` by multiple inheritance. Each method runs on a full
``Field`` at runtime, but a type checker sees only the defining mixin, which does
not declare the cross-cutting ``Field`` attributes (``self.name``, ``self.store``,
…) the method reaches through.

:class:`_FieldStubs` collects that surface so the mixins inherit a correct, typed
view (the model-mixin analogue is ``_ModelStubs``). It is purely a typing aid —
``if typing.TYPE_CHECKING:`` declarations and ``__slots__ = ()`` — so at runtime
it is an empty class contributing only a deduplicated MRO entry; :class:`Field`
provides the real defaults.

Scope: only the **plain attributes** ``Field`` declares with a stable type. The
properties (``column_type``/``is_column``/``base_field``) and the heavily
overridden ``convert_to_*`` methods are left out — their per-field-type overrides
make a single shared declaration unsafe.
"""

import typing

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import BaseModel, ModelLike
    from ..domain import Domain
    from ..primitives import ContextType
    from ..runtime import Environment


class _FieldStubs:
    """Shared, typing-only view of the ``Field`` attribute surface."""

    __slots__ = ()

    if typing.TYPE_CHECKING:
        # Plain class attributes set on Field (see orm/fields/base.py). Types
        # mirror Field's own annotations; the T-parameterised ``falsy_value`` and
        # the Field-valued ``inherited_field`` stay ``Any`` to avoid pulling the
        # generic / a forward ref into this typing-only base.
        name: str
        model_name: str
        string: str | None
        help: str | None
        type: str
        store: bool
        index: str | None
        translate: bool
        is_text: bool
        company_dependent: bool
        aggregator: str | None
        falsy_value: typing.Any
        inherited_field: typing.Any
        _column_type: tuple[str, str] | None

        # Subclass-declared attributes the model mixins read through a plain
        # ``Field``-typed variable (they guard on ``field.type`` /
        # ``field.relational``, which the type checker cannot narrow by).
        # Types mirror the real declarations: _Relational (relational/_base.py)
        # for bypass_search_access / check_company / context, Many2many for
        # relation / column1 / column2.
        bypass_search_access: bool
        check_company: bool
        context: ContextType
        relation: str | None
        column1: str | None
        column2: str | None

        # Shared Field methods the convert/sql mixins call through ``self``. Real
        # implementations own the cache-shape predicate and the company-dependent
        # fallback authority (see base.py); declared here so siblings reuse them.
        def _is_context_dependent(self, env: Environment) -> bool: ...
        def _company_dependent_fallback_raw(
            self, records: typing.Any
        ) -> typing.Any: ...

        # Subclass-defined methods the model mixins call through a plain
        # ``Field``-typed variable. Each signature mirrors the single real
        # implementation exactly (so it remains a valid override): _Relational /
        # One2many for get_comodel_domain, Monetary for get_currency_field,
        # Many2one for join, Properties for _add_default_values and
        # convert_to_read_multi, BaseString (textual.py) for
        # _get_stored_translations.
        def get_comodel_domain(self, model: ModelLike) -> Domain: ...
        def get_currency_field(self, model: ModelLike) -> str | None: ...
        def join(
            self, model: ModelLike, alias: str, query: Query
        ) -> tuple[BaseModel, str]: ...
        def _add_default_values(
            self, env: typing.Any, values: dict[str, typing.Any]
        ) -> list[typing.Any] | dict[str, typing.Any]: ...
        def convert_to_read_multi(
            self,
            values: list[typing.Any],
            records: ModelLike,
            use_display_name: bool = True,
        ) -> list[typing.Any]: ...
        def _get_stored_translations(
            self, record: BaseModel
        ) -> dict[str, str] | None: ...
