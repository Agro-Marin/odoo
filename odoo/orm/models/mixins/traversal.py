"""Traversal and transformation mixin for BaseModel.

Provides mapped, filtered, grouped, sorted, and update.
"""

import functools
import typing
from collections import defaultdict
from operator import itemgetter
from typing import Self

from odoo.libs._field_access import batch_cache_filter as _batch_cache_filter
from odoo.libs._field_access import batch_cache_get as _batch_cache_get
from odoo.libs._field_access import batch_group_ids as _batch_group_ids
from odoo.libs._field_access import sort_ids_by_cache as _sort_ids_by_cache
from odoo.libs.constants import PREFETCH_MAX
from odoo.tools import SQL
from odoo.tools.misc import PENDING, SENTINEL

from ... import decorators as api
from ..._recordset import is_recordset
from ..._typing import DomainType
from ...domain import Domain
from ...parsing import regex_order
from ._cache_scan import (
    caches_lang_dicts,
    can_scan_identity,
    can_scan_sorted,
    can_scan_truthy,
)
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Callable

T = typing.TypeVar("T")


@functools.total_ordering
class ReversibleComparator:
    """A comparator that supports reverse ordering and None handling."""

    __slots__ = ("__item", "__none_first", "__reverse")

    def __init__(self, item, reverse: bool, none_first: bool):
        self.__item = item
        self.__reverse = reverse
        self.__none_first = none_first

    def __lt__(self, other: ReversibleComparator) -> bool:
        item = self.__item
        item_cmp = other.__item
        if item is None:
            return False if item_cmp is None else self.__none_first
        if item_cmp is None:
            return not self.__none_first
        if item == item_cmp:
            return False
        if self.__reverse:
            item, item_cmp = item_cmp, item
        return item < item_cmp

    def __eq__(self, other) -> bool:
        if other.__class__ is not ReversibleComparator:
            return NotImplemented
        return self.__item == other.__item

    def __hash__(self):
        return hash(self.__item)

    def __repr__(self):
        return f"<ReversibleComparator {self.__item!r}{' reverse' if self.__reverse else ''}>"


class TraversalMixin(_ModelStubs):
    """Mixin providing traversal and transformation operations for recordsets."""

    __slots__ = ()

    @typing.overload
    def mapped(self, func: str) -> list[typing.Any]: ...

    @typing.overload
    def mapped(self, func: Callable[[Self], T]) -> list[T]: ...

    @api.private
    def mapped(self, func: str | Callable) -> list | Self:
        """Apply ``func`` on all records in ``self``, and return the result as a
        list or a recordset (if ``func`` return recordsets). In the latter
        case, the order of the returned recordset is arbitrary.

        :param func: a function or a dot-separated sequence of field names
        :return: self if func is falsy, result of func applied to all ``self`` records.

        .. code-block:: python3

            # returns a list of summing two fields for each record in the set
            records.mapped(lambda r: r.field1 + r.field2)

        The provided function can be a string to get field values:

        .. code-block:: python3

            # returns a list of names
            records.mapped("name")

            # returns a recordset of partners
            records.mapped("partner_id")

            # returns the union of all partner banks, with duplicates removed
            records.mapped("partner_id.bank_ids")
        """
        if not func:
            return self

        if isinstance(func, str):
            *rel_field_names, field_name = func.split(".")
            records = self
            for rel_field_name in rel_field_names:
                records = records[rel_field_name]
            if len(records) > PREFETCH_MAX:
                records.fetch([field_name])
            field = records._fields[field_name]
            getter = field.__get__
            if field.relational:
                return getter(records)
            if not records:
                return []
            # Check access on the WHOLE recordset, not records[:1]: a
            # record-sensitive override (res.users._has_field_access grants a
            # field on the current user's own record) would otherwise pass on
            # the first record and let the batch cache-read below serve other
            # records' restricted values unchecked. Matches ReadMixin._read_format.
            field.ensure_access(records)
            field.ensure_computed(records)
            field_cache = field._get_cache(records.env)
            _SENTINEL = SENTINEL
            _PENDING = PENDING
            _get = field_cache.get
            result = []
            _append = result.append
            if can_scan_identity(field):
                _none_val: typing.Any = field.convert_to_record(None, records[:1])
                result, miss_indices = _batch_cache_get(
                    field_cache, records._ids, PENDING, _none_val
                )
                if miss_indices:
                    rec_list = list(records)
                    for idx in miss_indices:
                        result[idx] = getter(rec_list[idx])
                return result
            else:
                _convert = field.convert_to_record
                for record in records:
                    value = _get(record._ids[0], _SENTINEL)
                    if value is not _SENTINEL and value is not _PENDING:
                        _append(_convert(value, record))
                    else:
                        _append(getter(record))
            return result

        if self:
            vals = [func(rec) for rec in self]
            if is_recordset(vals[0]):
                return vals[0].union(*vals[1:])
            return vals
        else:
            vals = func(self)
            return vals if is_recordset(vals) else []

    @api.private
    def filtered(self, func: str | Callable[[Self], bool] | Domain) -> Self:
        """Return the records in ``self`` satisfying ``func``.

        :param func: a function, Domain or a dot-separated sequence of field names
        :return: recordset of records satisfying func, may be empty.

        .. code-block:: python3

            # only keep records whose company is the current user's
            records.filtered(lambda r: r.company_id == user.company_id)

            # only keep records whose partner is a company
            records.filtered("partner_id.is_company")
        """
        if not func:
            return self
        if not self:
            return self
        if callable(func):
            pass
        elif isinstance(func, str):
            if "." in func:
                return self.browse(
                    rec_id
                    for rec_id, rec in zip(self._ids, self, strict=True)
                    if any(rec.mapped(func))
                )
            if func == "id":
                return self.browse([id_ for id_ in self._ids if id_])
            field = self._fields[func]
            if not can_scan_truthy(field):
                _field_get = field.__get__
                return self.browse(rec._ids[0] for rec in self if _field_get(rec))
            # Full recordset, not self[0:1] — see MappedMixin note above.
            field.ensure_access(self)
            field.ensure_computed(self)
            field_cache = field._get_cache(self.env)
            passing_ids, miss_indices = _batch_cache_filter(
                field_cache, self._ids, PENDING
            )
            if miss_indices:
                _field_get = field.__get__
                rec_list = list(self)
                for idx in miss_indices:
                    if _field_get(rec_list[idx]):
                        passing_ids.append(rec_list[idx]._ids[0])
                all_passing = set(passing_ids)
                passing_ids = [id_ for id_ in self._ids if id_ in all_passing]
            return self.browse(passing_ids)
        elif isinstance(func, Domain):
            return self.filtered_domain(func)
        else:
            raise TypeError(f"Invalid function {func!r} to filter on {self._name}")
        return self.browse(
            rec_id for rec_id, rec in zip(self._ids, self, strict=True) if func(rec)
        )

    @typing.overload
    def grouped(self, key: str) -> dict[typing.Any, Self]: ...

    @typing.overload
    def grouped(self, key: Callable[[Self], T]) -> dict[T, Self]: ...

    @api.private
    def grouped(self, key: str | Callable) -> dict:
        """Eagerly groups the records of ``self`` by the ``key``, returning a
        dict from the ``key``'s result to recordsets. All the resulting
        recordsets are guaranteed to be part of the same prefetch-set.

        Provides a convenience method to partition existing recordsets without
        the overhead of a :meth:`~._read_group`, but performs no aggregation.

        .. note:: unlike :func:`itertools.groupby`, does not care about input
                  ordering, however the tradeoff is that it can not be lazy

        :param key: either a callable from a :class:`Model` to a (hashable)
                    value, or a field name. In the latter case, it is equivalent
                    to ``itemgetter(key)`` (aka the named field's value)
        """
        if not self:
            return {}

        if isinstance(key, str):
            field = self._fields[key]
            if not field.relational:
                # Full recordset, not self[:1] — see MappedMixin note above.
                field.ensure_access(self)
                field.ensure_computed(self)
                field_cache = field._get_cache(self.env)
                _SENTINEL = SENTINEL
                _PENDING = PENDING
                _get = field_cache.get
                _field_get = field.__get__
                collator = defaultdict(list)
                if can_scan_identity(field):
                    _none_val: typing.Any = field.convert_to_record(None, self[:1])
                    ids = self._ids
                    results, miss_indices = _batch_cache_get(
                        field_cache, ids, PENDING, _none_val
                    )
                    if not miss_indices:
                        collator = _batch_group_ids(ids, results)
                    else:
                        miss_set = set(miss_indices)
                        rec_list = list(self)
                        collator = {}
                        for i, rec_id in enumerate(ids):
                            group_key = (
                                _field_get(rec_list[i]) if i in miss_set else results[i]
                            )
                            group = collator.get(group_key)
                            if group is None:
                                collator[group_key] = [rec_id]
                            else:
                                group.append(rec_id)
                else:
                    _convert = field.convert_to_record
                    for record in self:
                        rec_id = record._ids[0]
                        value = _get(rec_id, _SENTINEL)
                        if value is not _SENTINEL and value is not _PENDING:
                            try:
                                group_key = _convert(value, record)
                            except KeyError:
                                group_key = _field_get(record)
                        else:
                            group_key = _field_get(record)
                        collator[group_key].append(rec_id)
            else:
                key = itemgetter(key)
                collator = defaultdict(list)
                for record in self:
                    collator[key(record)].append(record._ids[0])
        else:
            collator = defaultdict(list)
            for record in self:
                collator[key(record)].append(record._ids[0])

        cls = type(self)
        env = self.env
        prefetch_ids = self._prefetch_ids
        return {
            key: cls(env, tuple(ids), prefetch_ids) for key, ids in collator.items()
        }

    @api.private
    def filtered_domain(self, domain: DomainType) -> Self:
        """Return the records in ``self`` satisfying the domain and keeping the same order.

        :param domain: :ref:`A search domain <reference/orm/domains>`.
        """
        if not self or not domain:
            return self
        predicate = Domain(domain)._as_predicate(self)
        return self.browse(
            rec_id
            for rec_id, rec in zip(self._ids, self, strict=True)
            if predicate(rec)
        )

    @api.private
    def sorted(
        self,
        key: str | Callable[[Self], typing.Any] | None = None,
        reverse: bool = False,
    ) -> Self:
        """Return the recordset ``self`` ordered by ``key``.

        :param key:
            It can be either of:

            * a function of one argument that returns a comparison key for each record
            * a string representing a comma-separated list of field names with optional
              NULLS (FIRST|LAST), and (ASC|DESC) directions
            * ``None``, in which case records are ordered according the default model's order
        :param reverse: if ``True``, return the result in reverse order

        .. code-block:: python3

            # sort records by name
            records.sorted(key=lambda r: r.name)
            # sort records by name in descending order, then by id
            records.sorted("name DESC, id")
            # sort records using default order
            records.sorted()

        .. note:: **Text order matches ``search(order=...)`` only under
            ``LC_COLLATE=C``.** This sorts by Python comparison (Unicode code
            point); ``ORDER BY`` sorts by the database's collation.  Odoo creates
            every database with ``LC_COLLATE 'C'``
            (``service/db.py::_create_empty_database``), where byte order and
            code-point order coincide and the two agree -- that equivalence is
            what makes this method safe to use interchangeably with a search.

            It does not hold on a database created outside Odoo, or from a
            configured ``db_template`` that is not itself ``C`` (PostgreSQL
            refuses to override a template's collation, so such a template
            propagates its own).  There ``es_ES.UTF-8`` orders ``apple, Apple,
            ápple`` and Python orders ``Apple, ápple, apple``; sort in SQL when
            the order is user-visible.
        """
        if len(self) < 2:
            return self
        if isinstance(key, str):
            order = key
            self._sorted_ensure_computed(order)
            ids = self._sorted_by_ids(order, reverse)
            if ids is not None:
                return self._spawn(self.env, ids, self._prefetch_ids)
            key = self._sorted_order_to_function(order)
        elif key is None:
            order = self._order
            self._sorted_ensure_computed(order)
            ids = self._sorted_by_ids(order, reverse)
            if ids is not None:
                return self._spawn(self.env, ids, self._prefetch_ids)
            key = self._sorted_order_to_function(order)
        ids = tuple(item._ids[0] for item in sorted(self, key=key, reverse=reverse))
        return self._spawn(self.env, ids, self._prefetch_ids)

    def _sorted_ensure_computed(self, order: str) -> None:
        """Pre-trigger access check + recomputation for all sort fields.

        Called before Python's ``sorted()`` so that each per-record key
        extraction can bypass ``__get__`` and read the cache directly.
        """
        _fields = self._fields
        for part in order.split(","):
            match = regex_order.match(part)
            if match:
                field = _fields.get(match["field"])
                if field is not None:
                    # Full recordset, not self[:1] — see MappedMixin note above.
                    field.ensure_access(self)
                    field.ensure_computed(self)

    def _sorted_by_ids(self, order: str, reverse: bool) -> tuple | None:
        """Try to sort ``self._ids`` directly from cache values.

        Handles single- and multi-field sorts, avoiding the N singleton records
        the general ``sorted(self, key=...)`` path requires.

        A multi-key sort is performed as **successive stable single-key sorts,
        least significant key first** -- the classic radix argument: a stable
        sort preserves the order established by the previous pass, so after the
        last (most significant) pass the sequence is in full lexicographic
        order.  That turns every column into another call of the same Rust
        primitive the single-key path already uses, instead of building N Python
        tuple keys, and it makes each column's direction independent, so the
        mixed-direction case no longer has to bail out to the record-based
        ``sorted(self, key=...)`` fallback (``"name desc, id asc"`` measured 31x
        faster, ``"sequence, id"`` -- the default ``_order`` of a great many
        models -- 4.7x).

        Correctness rests on the primitive being stable *and* applying
        ``reverse`` to the comparator rather than reversing the result, which is
        also CPython's ``list.sort`` semantics; both are pinned by
        ``test_sorted_multi_key.py``.

        :return: the sorted tuple of IDs, or ``None`` if the fast path does not
            apply (relational, property, boolean, or cache miss)
        """
        _PENDING = PENDING
        _fields = self._fields
        env = self.env

        sort_specs = []
        for part in order.split(","):
            match = regex_order.match(part)
            if not match:
                return None
            field_name = match["field"]
            if match["property"]:
                return None
            field = _fields.get(field_name)
            if field is None or not can_scan_sorted(field):
                return None
            desc = (match["direction"] or "").upper() == "DESC"
            nulls_raw = (match["nulls"] or "").upper()
            nulls_first = (nulls_raw == "NULLS FIRST") if nulls_raw else desc
            cache = None if field_name == "id" else field._get_cache(env)
            sort_specs.append((cache, desc, nulls_first))

        ids = self._ids
        for field_cache, desc, nulls_first in reversed(sort_specs):
            reverse_param = desc != reverse
            if field_cache is None:
                ids = tuple(sorted(ids, reverse=reverse_param))
                continue
            sorted_ids = _sort_ids_by_cache(
                field_cache, ids, _PENDING, reverse_param, nulls_first == desc
            )
            if sorted_ids is None:
                return None
            ids = sorted_ids
        return ids

    @api.model
    def _sorted_order_to_function(self, order: str) -> Callable[[Self], typing.Any]:
        _env = self.env

        def order_to_function(order_part):
            order_match = regex_order.match(order_part)
            if not order_match:
                raise ValueError(f"Invalid order {order!r} to sort")
            field_name = order_match["field"]
            property_name = order_match["property"]
            reverse = (order_match["direction"] or "").upper() == "DESC"
            nulls = (order_match["nulls"] or "").upper()
            if nulls:
                nulls_first = nulls == "NULLS FIRST"
            else:
                nulls_first = reverse

            field = self._fields[field_name]
            field_expr = (
                f"{field_name}.{property_name}" if property_name else field_name
            )
            if field.type == "many2one" and (
                not property_name or property_name == "id"
            ):
                seen = _env.context.get("__m2o_order_seen_sorted", ())
                if field in seen:
                    return lambda _: None
                comodel = _env[field.comodel_name].with_context(
                    __m2o_order_seen_sorted=frozenset((field, *seen))
                )
                func_comodel = comodel._sorted_order_to_function(
                    property_name or comodel._order
                )

                def getter(rec):
                    value = rec[field_name]
                    if not value:
                        return None
                    return func_comodel(value)

            elif field.relational:
                raise ValueError(
                    f"Invalid order on relational field {order_part!r} to sort"
                )
            elif field.type == "boolean":
                getter = field.expression_getter(field_expr)
            elif not property_name and not caches_lang_dicts(field, _env):
                _cache_get = field._get_cache(_env).get
                _field_get = field.__get__
                _S = SENTINEL
                _P = PENDING

                def getter(rec):
                    value = _cache_get(rec._ids[0], _S)
                    if value is _S or value is _P:
                        record_value = _field_get(rec)
                        value = field._get_cache(_env).get(rec._ids[0], _S)
                        if value is _S:
                            return record_value
                    return value if value is not False else None

            else:
                raw_getter = field.expression_getter(field_expr)

                def getter(rec):
                    value = raw_getter(rec)
                    return value if value is not False else None

            comparator = functools.partial(
                ReversibleComparator,
                reverse=reverse,
                none_first=nulls_first,
            )
            return lambda rec: comparator(getter(rec))

        item_makers = [order_to_function(order_part) for order_part in order.split(",")]
        if len(item_makers) == 1:
            return item_makers[0]
        return lambda rec: tuple(fn(rec) for fn in item_makers)

    @api.private
    def update(self, values: dict[str, typing.Any]) -> None:
        """Update the records in ``self`` with ``values``."""
        for name, value in values.items():
            self[name] = value

    def _has_cycle(self, field_name: str | None = None) -> bool:
        """Return whether the records in ``self`` form a loop along ``field_name``
        (default: the parent field).

        No EXCLUSIVE LOCK is taken (for performance), so concurrent transactions
        may still create loops.

        :param field_name: optional field name (default: ``self._parent_name``)
        :return: ``True`` if a loop was found
        """
        if not field_name:
            field_name = self._parent_name

        field = self._fields.get(field_name)
        if not field:
            raise ValueError(f"Invalid field_name: {field_name!r}")

        if not (
            field.type in ("many2many", "many2one")
            and field.comodel_name == self._name
            and field.store
        ):
            raise ValueError(
                f"Field must be a many2one or many2many relation on itself: {field_name!r}"
            )

        if not self.ids:
            return False

        self.flush_model([field_name])
        if field.type == "many2many":
            assert (
                field.relation is not None
                and field.column1 is not None
                and field.column2 is not None
            )
            relation = field.relation
            column1 = field.column1
            column2 = field.column2
        else:
            relation = self._table
            column1 = "id"
            column2 = field_name
        cr = self.env.cr
        cr.execute(
            SQL(
                """
            WITH RECURSIVE __reachability AS (
                SELECT %(col1)s AS source, %(col2)s AS destination
                FROM %(rel)s
                WHERE %(col1)s IN %(ids)s AND %(col2)s IS NOT NULL
            UNION
                SELECT r.source, t.%(col2)s
                FROM __reachability r
                JOIN %(rel)s t ON r.destination = t.%(col1)s AND t.%(col2)s IS NOT NULL
            )
            SELECT 1 FROM __reachability
            WHERE source = destination
            LIMIT 1
            """,
                ids=tuple(self.ids),
                rel=SQL.identifier(relation),
                col1=SQL.identifier(column1),
                col2=SQL.identifier(column2),
            )
        )
        return bool(cr.fetchone())
