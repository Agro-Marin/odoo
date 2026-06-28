"""Typing-only declaration of the shared ``Field`` surface.

``_FieldDescriptionMixin`` / ``_FieldConvertMixin`` / ``_FieldSqlMixin`` are
composed onto :class:`Field` by multiple inheritance (``class Field[T](
_FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin)``). Each method
operates on ``self`` — a full ``Field`` at runtime — but a type checker sees only
the *defining* mixin, which does not declare the cross-cutting ``Field``
attributes (``self.name``, ``self.store``, …) it reaches through.

:class:`_FieldStubs` collects that surface in one place; the field mixins inherit
it for a correct, typed view. The model-mixin analogue is ``_ModelStubs``.

This is purely a typing aid — declarations under ``if typing.TYPE_CHECKING:`` and
``__slots__ = ()`` — so at runtime it is an empty class contributing only a
(deduplicated) MRO entry; :class:`Field` provides the real defaults.

Scope: the **plain attributes** ``Field`` declares with a stable type. The
properties (``column_type``/``is_column``/``base_field``) and the heavily
subclass-overridden ``convert_to_*`` methods are deliberately left out — their
many per-field-type overrides make a single shared declaration unsafe.
"""

import typing

if typing.TYPE_CHECKING:
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

        # Shared Field method the convert/sql mixins call through ``self``. The
        # real implementation is the single owner of the cache-shape predicate
        # (see "The cache shape, owned in one place" in base.py); declaring it
        # here lets a sibling base use it instead of re-deriving the rule inline.
        def _is_context_dependent(self, env: Environment) -> bool: ...
