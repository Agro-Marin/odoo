"""Typing-only declaration of the shared ``BaseModel`` surface.

The model mixins (``WriteMixin``, ``CacheMixin``, …) are stateless
``__slots__ = ()`` fragments composed onto :class:`BaseModel` by multiple
inheritance. A type checker sees only the *defining* mixin class, which does not
declare the cross-cutting members (``self.env``, ``self._fields``, …) that live
on ``BaseModel``, producing spurious ``[attr-defined]`` errors.

:class:`_ModelStubs` collects that shared surface in **one** place, giving mixins
that inherit it a typed view of the recordset members they reach through. It is
*purely* a typing aid:

* ``__slots__ = ()`` — adds no instance layout, so it introduces no ``__dict__``
  and costs nothing.
* declarations live under ``if typing.TYPE_CHECKING:`` — at runtime the class body
  is empty, contributing only a (deduplicated) MRO entry.

The types here match what ``BaseModel`` declares (or the looser,
override-compatible types the pre-existing mixin stubs used). Shared recordset
*methods* (``browse``, ``filtered``, …) are declared too, so a mixin can call
them on ``self`` and chain on the ``Self`` result; each signature mirrors the
real implementation, keeping it a valid override.
"""

import typing

if typing.TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Collection,
        Iterable,
        Iterator,
        Mapping,
        Reversible,
    )
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
        env: typing.Any
        _ids: tuple
        _prefetch_ids: typing.Any

        pool: typing.Any
        _fields: Mapping[str, Field]
        _name: str
        _table: str
        id: int
        ids: list[int]
        _log_access: bool
        _active_name: str | None
        _parent_name: str
        _parent_store: bool

        _inherits: dict
        _inherits_children: set[str]
        _description: str
        _abstract: bool
        _auto: bool
        _order: str
        _rec_name: str | None
        _rec_names_search: list[str] | None
        _table_objects: dict
        _check_company_auto: bool

        def browse(self, ids: int | typing.Iterable[IdType] = ()) -> Self: ...
        def new(
            self,
            values: ValuesType | None = None,
            origin: Self | None = None,
            ref: str | None = None,
        ) -> Self: ...
        def ensure_one(self) -> Self: ...
        def exists(self) -> Self: ...
        def sudo(self, flag: bool = True) -> Self: ...
        def with_env(self, env: Environment) -> Self: ...
        def filtered(self, func: str | Callable[[Self], bool] | Domain) -> Self: ...
        def __iter__(self) -> Iterator[Self]: ...
        def __len__(self) -> int: ...
        @typing.overload
        def __getitem__(self, key: int | slice) -> Self: ...
        @typing.overload
        def __getitem__(self, key: str) -> typing.Any: ...
        def __getitem__(self, key: int | slice | str) -> Self | typing.Any: ...

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
        def _check_company(self, fnames: Collection[str] | None = None) -> None: ...
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
        def _compute_field_value(self, field: Field) -> None: ...
        def invalidate_recordset(
            self, fnames: Collection[str] | None = None, flush: bool = True
        ) -> None: ...
        def flush_recordset(self, fnames: Collection[str] | None = None) -> None: ...
        def _table_has_rows(self) -> bool: ...
        def _init_column(self, column_name: str) -> None: ...
        @classmethod
        def is_transient(cls) -> bool: ...
        def _get_base_lang(self) -> str: ...
        def _convert_to_cache_properties_definition(
            self, value: typing.Any
        ) -> typing.Any: ...
        def _convert_to_column_properties_definition(
            self, value: typing.Any
        ) -> typing.Any: ...
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

        @property
        def _origin(self) -> Self: ...
        @property
        def _has_origin(self) -> bool: ...
        @property
        def _table_sql(self) -> SQL: ...
        @property
        def _onchange_methods(self) -> dict[str, list]: ...
