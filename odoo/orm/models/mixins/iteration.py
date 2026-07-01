"""Iteration and set-operation mixin for BaseModel.

Iterating over recordsets, combining them, and set operations (union,
intersection, difference).
"""

import typing
import warnings
from itertools import batched
from typing import Self

from odoo.libs.constants import PREFETCH_MAX
from odoo.tools import OrderedSet
from odoo.tools.misc import ReversedIterable

from ... import decorators as api
from ...helpers import _origin_ids
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Iterator, Reversible

    from ..._typing import IdType
    from ...runtime import Environment


class IterationMixin(_ModelStubs):
    """Mixin providing iteration and set operations for recordsets."""

    __slots__ = ()

    # A recordset is an ordered collection of records in a given environment.
    # It holds the env and a tuple of ids; values live in the global cache,
    # keyed by id.  This makes cache access direct, allows id-less new records,
    # and keeps the global cache a pure index.

    def __init__(
        self,
        env: Environment,
        ids: tuple[IdType, ...],
        prefetch_ids: Reversible[IdType],
    ):
        """Create a recordset instance.

        :param env: an environment
        :param ids: a tuple of record ids
        :param prefetch_ids: a reversible iterable of record ids (for prefetching)

        .. note::
            Recordsets are normally built via :meth:`_spawn` (or :meth:`browse`),
            which bypass this ``__init__``.  ``_spawn`` is the single source of
            truth for the slot set; a handful of per-record hot loops still
            inline the same three assignments for speed (``__iter__``,
            ``__reversed__``, ``CacheMixin._flush``, ``Environment.__getitem__``)
            and are marked as such.  Any new slot must be set in ``_spawn`` and
            those marked mirrors, or empty recordsets will lack it.
        """
        self.env = env
        self._ids = ids
        self._prefetch_ids = prefetch_ids

    @classmethod
    def _spawn(
        cls,
        env: Environment,
        ids: tuple[IdType, ...],
        prefetch_ids: Reversible[IdType],
    ) -> Self:
        """Build a recordset without the ``__init__`` dispatch overhead.

        Single source of truth for recordset construction: it sets exactly the
        :attr:`BaseModel.__slots__`.  Use it instead of hand-rolling
        ``object.__new__(cls)`` + slot assignments, so adding a slot is a
        one-line change here rather than a hunt across every construction site.
        Hot per-record loops may still inline the body (see ``__init__``).
        """
        record = object.__new__(cls)
        record.env = env
        record._ids = ids
        record._prefetch_ids = prefetch_ids
        return record

    @api.private
    def browse(self, ids: int | typing.Iterable[IdType] = ()) -> Self:
        """Return a recordset for the ids provided as parameter in the current
        environment.

        .. code-block:: python

            self.browse([7, 18, 12])
            res.partner(7, 18, 12)
        """
        if not ids:
            ids = ()
        elif ids.__class__ is int:
            ids = (ids,)
        elif ids.__class__ is not tuple:
            ids = tuple(ids)
        return self._spawn(self.env, ids, ids)

    # Internal properties

    @property
    def ids(self) -> list[int]:
        """Return the list of actual record ids corresponding to ``self``."""
        if all(self._ids):
            return list(self._ids)  # already real records
        return list(_origin_ids(self._ids))

    # "Dunder" methods

    def __bool__(self) -> bool:
        """Test whether ``self`` is nonempty."""
        return bool(self._ids)

    def __len__(self) -> int:
        """Return the size of ``self``."""
        return len(self._ids)

    def __iter__(self) -> Iterator[Self]:
        """Return an iterator over ``self``."""
        ids = self._ids
        size = len(ids)
        if size <= 1:
            # 0 or 1 record: avoid the allocation below.
            if size == 1:
                yield self
            return
        # HOT per-record loop: inline mirror of `_spawn` (keep slot assignments
        # in sync), bypassing the method call and type.__call__ dispatch chain.
        _new = object.__new__
        cls = self.__class__
        env = self.env
        prefetch_ids = self._prefetch_ids
        if size > PREFETCH_MAX and prefetch_ids is ids:
            for sub_ids in batched(ids, PREFETCH_MAX, strict=False):
                for id_ in sub_ids:
                    rs = _new(cls)
                    rs.env = env
                    rs._ids = (id_,)
                    rs._prefetch_ids = sub_ids
                    yield rs
        else:
            for id_ in ids:
                rs = _new(cls)
                rs.env = env
                rs._ids = (id_,)
                rs._prefetch_ids = prefetch_ids
                yield rs

    def __reversed__(self) -> Iterator[Self]:
        """Return a reversed iterator over ``self``."""
        # mirror of __iter__ (HOT per-record loop: inline mirror of `_spawn`)
        ids = self._ids
        size = len(ids)
        if size <= 1:
            if size == 1:
                yield self
            return
        _new = object.__new__
        cls = self.__class__
        env = self.env
        prefetch_ids = self._prefetch_ids
        if size > PREFETCH_MAX and prefetch_ids is ids:
            for sub_ids in batched(reversed(ids), PREFETCH_MAX, strict=False):
                for id_ in sub_ids:
                    rs = _new(cls)
                    rs.env = env
                    rs._ids = (id_,)
                    rs._prefetch_ids = sub_ids
                    yield rs
        else:
            prefetch_ids = ReversedIterable(prefetch_ids)
            for id_ in reversed(ids):
                rs = _new(cls)
                rs.env = env
                rs._ids = (id_,)
                rs._prefetch_ids = prefetch_ids
                yield rs

    def __contains__(self, item) -> bool:
        """Test whether ``item`` (record or field name) is an element of ``self``.

        In the first case, the test is fully equivalent to::

            any(item == record for record in self)

        In the second case, we check whether the model has a field named
        ``item``.
        """
        try:
            if self._name == item._name:
                return len(item) == 1 and item.id in self._ids
            raise TypeError(f"inconsistent models in: {item} in {self}")
        except AttributeError:
            if isinstance(item, str):
                return item in self._fields
            raise TypeError(f"unsupported operand types in: {item!r} in {self}") from None

    @api.private
    def index(self, item, start: int = 0, stop: int | None = None) -> int:
        """Return the first index where the singleton ``item`` is found in ``self``.

        Honors the standard ``Sequence.index`` contract: raises ``ValueError``
        when not found.  ``item`` must be a singleton recordset of the same
        model as ``self``.
        """
        try:
            if self._name != item._name:
                raise TypeError(f"inconsistent models in: {item}.index({self})")
        except AttributeError:
            raise TypeError(
                f"unsupported operand types in: {item!r}.index({self})"
            ) from None
        if len(item) != 1:
            raise ValueError(f"index requires a singleton, got {len(item)} records")
        target = item.id
        ids = self._ids
        n = len(ids)
        # Normalize negative offsets like ``list.index``, else index(rec, -1)
        # would return -1 verbatim and break the Sequence contract.
        if start < 0:
            start = max(0, n + start)
        if stop is None:
            stop = n
        elif stop < 0:
            stop = max(0, n + stop)
        for i in range(start, stop):
            if ids[i] == target:
                return i
        raise ValueError(f"{item} is not in recordset")

    @api.private
    def count(self, item) -> int:
        """Return the number of occurrences of the singleton ``item`` in ``self``.

        Honors the standard ``Sequence.count`` contract.  ``item`` must be a
        singleton recordset of the same model as ``self``.
        """
        try:
            if self._name != item._name:
                raise TypeError(f"inconsistent models in: {item}.count({self})")
        except AttributeError:
            raise TypeError(
                f"unsupported operand types in: {item!r}.count({self})"
            ) from None
        if len(item) != 1:
            raise ValueError(f"count requires a singleton, got {len(item)} records")
        target = item.id
        return sum(1 for id_ in self._ids if id_ == target)

    def __add__(self, other) -> Self:
        """Return the concatenation of two recordsets."""
        return self.concat(other)

    @api.private
    def concat(self, *args: Self) -> Self:
        """Return the concatenation of ``self`` with all the arguments (in
        linear time complexity).
        """
        ids = list(self._ids)
        for arg in args:
            try:
                if arg._name != self._name:
                    raise TypeError(f"inconsistent models in: {self} + {arg}")
                ids.extend(arg._ids)
            except AttributeError:
                raise TypeError(f"unsupported operand types in: {self} + {arg!r}") from None
        return self.browse(ids)

    def __sub__(self, other) -> Self:
        """Return the recordset of all the records in ``self`` that are not in
        ``other``. Note that recordset order is preserved.
        """
        try:
            if self._name != other._name:
                raise TypeError(f"inconsistent models in: {self} - {other}")
            # fast paths: empty operands avoid set creation
            if not other._ids or not self._ids:
                return self
            other_ids = set(other._ids)
            return self.browse(id_ for id_ in self._ids if id_ not in other_ids)
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} - {other!r}") from None

    def __and__(self, other) -> Self:
        """Return the intersection of two recordsets.
        Note that first occurrence order is preserved.
        """
        try:
            if self._name != other._name:
                raise TypeError(f"inconsistent models in: {self} & {other}")
            # fast paths: empty operands
            if not self._ids or not other._ids:
                return self.browse()
            other_ids = set(other._ids)
            return self.browse(OrderedSet(id_ for id_ in self._ids if id_ in other_ids))
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} & {other!r}") from None

    def __or__(self, other) -> Self:
        """Return the union of two recordsets.
        Note that first occurrence order is preserved.
        """
        return self.union(other)

    @api.private
    def union(self, *args: Self) -> Self:
        """Return the union of ``self`` with all the arguments (in linear time
        complexity, with first occurrence order preserved).
        """
        # fast path: single argument union (the common case for `self | other`)
        if len(args) == 1:
            arg = args[0]
            try:
                if arg._name != self._name:
                    raise TypeError(f"inconsistent models in: {self} | {arg}")
            except AttributeError:
                raise TypeError(f"unsupported operand types in: {self} | {arg!r}") from None
            if not arg._ids:
                # self may carry duplicates (from concat / +); union preserves
                # first-occurrence order and dedups, so match the general path
                # rather than returning self raw. Fast path keeps identity when
                # self is already unique (the overwhelming common case).
                if len(self._ids) == len(set(self._ids)):
                    return self
                return self.browse(OrderedSet(self._ids))
            if not self._ids:
                # browse() to keep self's env; returning arg would leak arg's
                # env (e.g. company context) into the result.
                return self.browse(OrderedSet(arg._ids))
            return self.browse(OrderedSet(self._ids + arg._ids))

        ids = list(self._ids)
        for arg in args:
            try:
                if arg._name != self._name:
                    raise TypeError(f"inconsistent models in: {self} | {arg}")
                ids.extend(arg._ids)
            except AttributeError:
                raise TypeError(f"unsupported operand types in: {self} | {arg!r}") from None
        return self.browse(OrderedSet(ids))

    def __eq__(self, other: object) -> bool:
        """Test whether two recordsets are equivalent (up to reordering)."""
        try:
            if self._name != other._name:
                return False
            s_ids = self._ids
            o_ids = other._ids
            # fast paths: identity and equal id-tuples
            if s_ids is o_ids or s_ids == o_ids:
                return True
            # Compare as SETS of ids ("up to reordering").  ``_ids`` may hold
            # duplicates (concat/+), so ``rec + rec`` must equal ``rec``; this
            # is consistent with ``__hash__`` (frozenset of ids).
            return set(s_ids) == set(o_ids)
        except AttributeError:
            if other:
                warnings.warn(
                    f"unsupported operand type(s) for \"==\": '{self._name}()' == '{other!r}'",
                    stacklevel=2,
                )
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        try:
            if self._name == other._name:
                # Proper subset over de-duplicated ids; raw tuple lengths are
                # wrong when ``_ids`` has duplicates (concat/+).
                return set(self._ids) < set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __le__(self, other: object) -> bool:
        try:
            if self._name == other._name:
                # cheap checks first: empty or singleton subset
                if not self or self in other:
                    return True
                return set(self._ids) <= set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        try:
            if self._name == other._name:
                # proper superset over de-duplicated ids; raw tuple lengths
                # are wrong when ``_ids`` contains duplicates (see __lt__).
                return set(self._ids) > set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        try:
            if self._name == other._name:
                if not other or other in self:
                    return True
                return set(self._ids) >= set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __int__(self) -> int:
        return self.id or 0

    def __repr__(self) -> str:
        return f"{self._name}{self._ids!r}"

    def __hash__(self) -> int:
        return hash((self._name, frozenset(self._ids)))

    def __deepcopy__(self, memo: dict) -> Self:
        return self

    @typing.overload
    def __getitem__(self, key: int | slice) -> Self: ...

    @typing.overload
    def __getitem__(self, key: str) -> typing.Any: ...

    def __getitem__(self, key: int | slice | str) -> Self | typing.Any:
        """Index with an int/slice to select records, or with a field name to
        read that field's value (``self`` must then be a single record).
        """
        if isinstance(key, str):
            # important: one must call the field's getter
            return self._fields[key].__get__(self)
        elif isinstance(key, slice):
            ids = self._ids[key]
            return self._spawn(self.env, ids, ids)
        else:
            ids = (self._ids[key],)
            return self._spawn(self.env, ids, self._prefetch_ids)

    def __setitem__(self, key: str, value: typing.Any):
        """Assign the field ``key`` to ``value`` in record ``self``."""
        # important: one must call the field's setter
        return self._fields[key].__set__(self, value)
