"""Typing-only declaration of the shared ``BaseModel`` surface.

The model mixins (``WriteMixin``, ``CacheMixin``, …) are written as stateless
``__slots__ = ()`` fragments that are composed onto :class:`BaseModel` by
multiple inheritance. Each mixin method operates on ``self`` — a full recordset
at runtime — but a type checker sees only the *defining* mixin class, which does
not declare the cross-cutting members (``self.env``, ``self._fields``, …) that
live on ``BaseModel``. That produced hundreds of spurious ``[attr-defined]``
errors, previously suppressed by re-declaring the same handful of stubs inside
six individual mixins (``access``/``export``/``load``/``schema``/``search``/
``translation``).

:class:`_ModelStubs` collects that shared surface in **one** place. Mixins that
inherit it gain a correct, typed view of the recordset members they reach
through. It is *purely* a typing aid:

* ``__slots__ = ()`` — it adds no instance layout, so composing it onto a
  ``__slots__``-based mixin does not introduce ``__dict__`` and costs nothing.
* the declarations live under ``if typing.TYPE_CHECKING:`` — at runtime the class
  body is empty, so it contributes nothing but a (deduplicated) MRO entry.

``BaseModel`` provides the real values during model setup; the types here match
what ``BaseModel`` declares (or the looser, override-compatible types the
pre-existing mixin stubs used for the slots ``BaseModel`` leaves unannotated).
The shared recordset *methods* (``browse``, ``filtered``, …) are declared too, so
a mixin can call them on ``self`` and chain on the ``Self`` result. Each signature
mirrors the single real implementation on its owning mixin, so that method stays a
valid override.
"""

import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Reversible
    from typing import Self

    from odoo.tools import SQL, Query

    from ..._typing import DomainType, IdType, ValuesType
    from ...domain import Domain
    from ...fields.base import Field
    from ...runtime import Environment


class _ModelStubs:
    """Shared, typing-only view of the ``BaseModel`` recordset surface."""

    __slots__ = ()

    if typing.TYPE_CHECKING:
        # Instance slots on BaseModel (``__slots__ = ["_ids", "_prefetch_ids",
        # "env"]``); ``env`` stays ``Any`` — Environment is Layer 3 and the
        # pre-existing stubs deliberately did not pull it across the boundary.
        env: typing.Any
        _ids: tuple
        _prefetch_ids: typing.Any

        # Registry / model metadata set during registration.
        pool: typing.Any
        _fields: dict
        _name: str
        _table: str
        id: int
        ids: list[int]
        _log_access: bool
        _active_name: str | None
        _parent_name: str
        _parent_store: bool

        # Model-definition class attributes (``_name = ...`` & friends).
        _inherits: dict
        _description: str
        _abstract: bool
        _auto: bool
        _order: str
        _rec_name: str | None
        _rec_names_search: list[str] | None
        _table_objects: dict
        _check_company_auto: bool

        # Recordset operations whose single real implementation lives on a
        # sibling mixin (browse -> IterationMixin, sudo/with_env/ensure_one ->
        # EnvironmentMixin, filtered -> TraversalMixin, exists -> SearchMixin).
        # Declaring them here lets any mixin call them on ``self`` and chain on
        # the ``Self`` result; the signatures mirror the real ones exactly so
        # those remain valid overrides.
        def browse(self, ids: int | typing.Iterable[IdType] = ()) -> Self: ...
        def ensure_one(self) -> Self: ...
        def exists(self) -> Self: ...
        def sudo(self, flag: bool = True) -> Self: ...
        def with_env(self, env: Environment) -> Self: ...
        def filtered(self, func: str | Callable[[Self], bool] | Domain) -> Self: ...
        def __iter__(self) -> Iterator[Self]: ...

        # The ``with_*`` rebinding family + set algebra (all EnvironmentMixin /
        # IterationMixin), likewise returning a recordset.
        def with_context(
            self, ctx: dict[str, typing.Any] | None = None, /, **overrides
        ) -> Self: ...
        def with_user(self, user) -> Self: ...
        def with_company(self, company: Self | int | None) -> Self: ...
        def with_prefetch(
            self, prefetch_ids: Reversible[IdType] | None = None
        ) -> Self: ...
        def union(self, *args: Self) -> Self: ...
        def concat(self, *args: Self) -> Self: ...

        # Query/SQL entry points (SearchMixin / AccessMixin) that other mixins —
        # notably the read_group pipeline — call through ``self``.
        def check_access(self, operation: str) -> None: ...
        def _search(
            self,
            domain: DomainType,
            offset: int = 0,
            limit: int | None = None,
            order: str | None = None,
            *,
            active_test: bool = True,
            bypass_access: bool = False,
        ) -> Query: ...
        def _field_to_sql(
            self, alias: str, field_expr: str, query: Query | None = None
        ) -> SQL: ...

        # CRUD / persistence entry points other mixins call through ``self``.
        def write(self, vals: ValuesType) -> typing.Literal[True]: ...
        def fetch(self, field_names: Collection[str] | None = None) -> None: ...
        def flush_model(self, fnames: Collection[str] | None = None) -> None: ...
        def filtered_domain(self, domain: DomainType) -> Self: ...
        def _validate_fields(
            self, field_names: Iterable[str], excluded_names: Iterable[str] = ()
        ) -> None: ...
        def get_property_definition(self, full_name: str) -> dict: ...
        def _has_field_access(
            self, field: Field, operation: typing.Literal["read", "write"]
        ) -> bool: ...
        def _check_field_access(
            self, field: Field, operation: typing.Literal["read", "write"]
        ) -> None: ...
        def _check_company(self, fnames: list[str] | None = None) -> None: ...
        def modified(
            self,
            fnames: Collection[str],
            create: bool = False,
            before: bool = False,
        ) -> None: ...
        def _modified_before(self, fnames: Collection[str]) -> None: ...
        def _recompute_recordset(
            self, fnames: Collection[str] | None = None
        ) -> None: ...
        def invalidate_recordset(
            self, fnames: Collection[str] | None = None, flush: bool = True
        ) -> None: ...
        def flush_recordset(self, fnames: Collection[str] | None = None) -> None: ...
        def _determine_fields_to_fetch(
            self,
            field_names: Collection[str] | None = None,
            ignore_when_in_cache: bool = False,
        ) -> list[Field]: ...
        @classmethod
        def _spawn(
            cls,
            env: Environment,
            ids: tuple[IdType, ...],
            prefetch_ids: Reversible[IdType],
        ) -> Self: ...

        # Read-only properties on BaseModel / EnvironmentMixin that sibling
        # mixins read through ``self`` — declared as properties (not plain
        # attributes) so the real read-only properties remain valid overrides.
        @property
        def _origin(self) -> Self: ...
        @property
        def _table_sql(self) -> SQL: ...
        @property
        def _onchange_methods(self) -> dict[str, list]: ...
