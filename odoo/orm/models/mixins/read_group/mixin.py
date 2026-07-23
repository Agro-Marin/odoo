"""Core read_group mixin — main entry points.

``ReadGroupMixin`` exposes the public methods (``_read_group``,
``_read_grouping_sets``, ``_read_group_empty_value``, deprecated ``read_group``)
and inherits SQL/format/fill logic from the sub-mixins in this package.
"""

import inspect
import itertools
import typing
from collections import defaultdict

from odoo.tools import SQL, Query, unique

from .... import decorators as api
from ...._typing import DomainType
from ....constants import READ_GROUP_AGGREGATE
from ....domain import Domain
from ....helpers import itemgetter_tuple
from ....parsing import parse_read_group_spec, regex_field_agg
from .fill import _ReadGroupFillMixin
from .format import _ReadGroupFormatMixin
from .sql import _ReadGroupSQLMixin

if typing.TYPE_CHECKING:
    from collections.abc import Sequence


class ReadGroupMixin(_ReadGroupSQLMixin, _ReadGroupFormatMixin, _ReadGroupFillMixin):
    """Grouping/aggregation methods inherited by BaseModel.

    SQL generation, formatting, and fill logic live in dedicated sub-mixins.
    """

    __slots__ = ()

    @api.model
    def _read_grouping_sets(
        self,
        domain: DomainType,
        grouping_sets: Sequence[Sequence[str]],
        aggregates: Sequence[str] = (),
        order: str | None = None,
    ) -> list[list[tuple]]:
        """Aggregate with several groupings in one query when possible.

        Uses SQL ``GROUPING SETS`` as an efficient alternative to calling
        :meth:`~._read_group` once per ``groupby``, getting several aggregation
        levels in one round-trip. many2many groupbys may still need extra SQL
        because of deduplicated rows.

        :param domain: :ref:`a search domain <reference/orm/domains>`
        :param grouping_sets: list of ``groupby`` specs, each like the ``groupby``
            of :meth:`~._read_group`, e.g. ``[['partner_id'], ['partner_id',
            'state']]``.
        :param aggregates: list of ``'field:agg'`` specs. ``agg`` is one of the
            allow-listed aggregates in ``odoo.orm.constants.READ_GROUP_AGGREGATE``
            (``sum``, ``avg``, ``max``, ``min``, ``bool_and``, ``bool_or``,
            ``array_agg``, ``array_agg_distinct``, ``count``, ``count_distinct``,
            ``any_value``, or ``recordset`` — ``array_agg`` as a recordset), or
            ``sum_currency`` (monetary fields only).
        :param order: optional ``order by`` overriding the natural group order;
            see also :meth:`~.search`.
        :return: list of lists of tuples mirroring *grouping_sets*; each inner
            list holds the rows for one grouping spec, each row being grouped
            values followed by aggregate values, in spec order. E.g. for
            ``grouping_sets=[['foo'], ['foo', 'bar']]`` and
            ``aggregates=['baz:sum']``::

                    [
                        [(foo1_val, baz_sum_1), (foo2_val, baz_sum_2), ...],
                        [
                            (foo1_val, bar1_val, baz_sum_3),
                            (foo2_val, bar2_val, baz_sum_4),
                            ...,
                        ],
                    ]

        :raise AccessError: if user is not allowed to access requested information
        """
        if not grouping_sets:
            msg = "The 'grouping_sets' parameter cannot be empty."
            raise ValueError(msg)

        query = self._search(domain)
        result = [[] for __ in grouping_sets]
        if query.is_empty():
            # Still validate the specs and field-level read access: an
            # unauthorized (or invalid) spec must raise the same error whether
            # or not the domain matches records.
            self._check_read_group_spec_access(
                itertools.chain.from_iterable(grouping_sets), aggregates
            )
            return result

        # grouping_sets: [(a, b), (a), ()]
        # all_groupby_specs: (a, b)
        all_groupby_specs = tuple(
            unique(spec for groupby in grouping_sets for spec in groupby)
        )

        # Many2many handling
        many2many_groupby_specs = []
        if len(grouping_sets) > 1:  # only relevant with multiple groupings
            many2many_groupby_specs.extend(
                spec
                for spec in all_groupby_specs
                if self._groupby_spec_might_duplicate_rows(self, spec)
            )

        if (
            many2many_groupby_specs
            and
            # Aggregates sensitive to row duplication (sum, avg) need M2M
            # groupings isolated.
            any(
                not aggregate.endswith(
                    (
                        ":max",
                        ":min",
                        ":bool_and",
                        ":bool_or",
                        ":array_agg_distinct",
                        ":recordset",
                        ":count_distinct",
                    ),
                )
                for aggregate in aggregates
                if aggregate != "__count"
            )
        ):
            # Recursive decomposition: prevent M2M joins from corrupting
            # aggregates in other grouping sets. For each combination of M2M
            # fields, sub-call the grouping sets sharing that exact combination.

            # ['A', 'B', 'C'] => [('A', 'B', 'C'), ('A', 'B'), ('A', 'C'), ('B', 'C'), ('A',), ('B',), ('C',), ()]
            m2m_combinaisons = (
                groupby
                for i in range(len(many2many_groupby_specs), -1, -1)
                for groupby in itertools.combinations(many2many_groupby_specs, i)
            )

            grouping_sets_to_process = dict(enumerate(grouping_sets))
            batched_calls = []  # [([result_index, ...], [groupby, ...])]

            for m2m_comb in m2m_combinaisons:
                if not grouping_sets_to_process:
                    break
                sub_grouping_sets = []
                sub_result_indexes = []
                for i, groupby in list(grouping_sets_to_process.items()):
                    if all(m2m in groupby for m2m in m2m_comb):
                        sub_grouping_sets.append(groupby)
                        sub_result_indexes.append(i)
                        grouping_sets_to_process.pop(i)

                if sub_grouping_sets:
                    batched_calls.append((sub_result_indexes, sub_grouping_sets))

            # raise (not assert) so this holds under python -O: a bug in the
            # m2m_combinaisons loop must not silently drop grouping sets.
            if grouping_sets_to_process:
                raise RuntimeError(
                    f"M2M decomposition lost grouping sets: "
                    f"{list(grouping_sets_to_process.values())}"
                )
            # If decomposed, make recursive calls and assemble results.
            if len(batched_calls) > 1:
                for indexes, sub_grouping_sets in batched_calls:
                    sub_order_parts = []
                    all_sub_groupby = {
                        spec for groupby in sub_grouping_sets for spec in groupby
                    }
                    for order_part in (order or "").split(","):
                        order_part = order_part.strip()
                        # Match the *whole* spec, not a prefix: a bare
                        # startswith(spec) wrongly drops e.g. ``tag_id desc``
                        # when another set groups by the prefix spec ``tag``.
                        if not any(
                            order_part == spec or order_part.startswith(f"{spec} ")
                            for spec in all_groupby_specs
                            if spec not in all_sub_groupby
                        ):
                            sub_order_parts.append(order_part)

                    sub_results = self._read_grouping_sets(
                        domain,
                        sub_grouping_sets,
                        aggregates=aggregates,
                        order=",".join(sub_order_parts),
                    )
                    # One entry per input grouping set; strict=True surfaces a
                    # contract violation instead of leaving result[index] unset.
                    for index, subresult in zip(indexes, sub_results, strict=True):
                        result[index] = subresult
                return result

        elif many2many_groupby_specs and "__count" in aggregates:
            # Common case: handle '__count' with M2M via a distinct count on
            # 'id', avoiding another _read_grouping_sets call.
            aggregates = tuple(
                aggregate if aggregate != "__count" else "id:count_distinct"
                for aggregate in aggregates
            )
            if order:
                # token-anchored replace (not str.replace): only rewrite an
                # order term whose spec is exactly '__count', so a field named
                # e.g. 'line__count' is not corrupted.
                parts = []
                for part in order.split(","):
                    part = part.strip()
                    if part == "__count" or part.startswith("__count "):
                        part = "id:count_distinct" + part[len("__count") :]
                    parts.append(part)
                order = ", ".join(parts)

        # SQL query construction
        groupby_terms: dict[str, SQL] = {
            spec: self._read_group_groupby(self._table, spec, query)
            for spec in all_groupby_specs
        }
        aggregates_terms: list[SQL] = [
            self._read_group_select(spec, query) for spec in aggregates
        ]
        if groupby_terms:
            # grouping_select_sql: GROUPING(a, b)
            grouping_select_sql = SQL(
                "GROUPING(%s)", SQL(", ").join(unique(groupby_terms.values()))
            )
        else:
            # GROUPING() is invalid SQL, so we use the 0 as literal
            grouping_select_sql = SQL("0")

        select_args = [
            grouping_select_sql,
            *groupby_terms.values(),
            *aggregates_terms,
        ]

        # grouping_select_sql and select_args snapshotted groupby_terms.values()
        # above; _read_group_orderby only replaces dict values in place, so
        # positions (and the positional GROUPING() masks) stay aligned.
        query.order = self._read_group_orderby(order, groupby_terms, query)
        # GROUPING SET ((a, b), (a), ())
        grouping_sets_sql = [
            SQL(
                "(%s)",
                SQL(", ").join(
                    groupby_terms[groupby_spec] for groupby_spec in grouping_set
                ),
            )
            for grouping_set in grouping_sets
        ]
        query.groupby = SQL(
            "GROUPING SETS (%s)", SQL(", ").join(unique(grouping_sets_sql))
        )

        # Extra ORDER BY columns needed in GROUP BY were already folded into
        # groupby_terms by _read_group_orderby, so grouping_sets_sql includes
        # them. (The default path wraps such columns in ANY_VALUE() instead.)

        # row_values: [(GROUPING(...), a1, b1, aggregates...), ...]
        row_values = self.env.execute_query(query.select(*select_args))
        if not row_values:  # shortcut
            return result

        return self._read_grouping_sets_dispatch_rows(
            row_values, grouping_sets, all_groupby_specs, aggregates, groupby_terms, result
        )

    def _groupby_spec_might_duplicate_rows(self, model, spec) -> bool:
        """Whether grouping by *spec* on *model* can duplicate rows (m2m/tags).

        Recurses through a dotted many2one path down to its comodel.
        """
        fname, property_name, __ = parse_read_group_spec(spec)
        field = model._fields[fname]
        if field.type == "properties":
            definition = self.get_property_definition(f"{fname}.{property_name}")
            property_type = definition.get("type")
            return property_type in ("tags", "many2many")

        if property_name:
            # raise (not assert) so this holds under python -O: a malformed spec
            # must not silently look up the wrong comodel.
            if field.type != "many2one":
                raise TypeError(
                    f"Field {fname!r} on {model._name!r}: dotted groupby spec "
                    f"only supported for many2one, got {field.type!r}"
                )
            return self._groupby_spec_might_duplicate_rows(
                self.env[field.comodel_name], property_name
            )

        return field.type == "many2many"

    def _read_grouping_sets_dispatch_rows(
        self,
        row_values: list[tuple],
        grouping_sets: Sequence[Sequence[str]],
        all_groupby_specs: Sequence[str],
        aggregates: Sequence[str],
        groupby_terms: dict[str, SQL],
        result: list[list[tuple]],
    ) -> list[list[tuple]]:
        """Split the ``GROUPING SETS`` rows back into per-grouping-set results.

        Each row carries a ``GROUPING()`` bitmask identifying which grouping set
        it belongs to; this maps every mask to its target result list and the
        column extractor, then dispatches the (column-transposed) rows.
        """
        # The GROUPING() integer keys each row to its user grouping set.
        aggregates_indexes = tuple(
            range(len(all_groupby_specs), len(all_groupby_specs) + len(aggregates))
        )

        # {GROUPING() bitmask: (append_method, extractor_method)}
        mask_grouping_mapping = {}

        # Map each unique GROUP BY term to its bitmask bit. Terms are reversed
        # because PostgreSQL computes the bitmask right-to-left (LSB first).
        # https://www.postgresql.org/docs/17/functions-aggregate.html#Grouping-Operations
        # NB: deduplicate BEFORE reversing so bit positions match GROUPING(),
        # which is built from unique() in forward order: with duplicated terms,
        # unique(reversed(...)) would keep the LAST forward occurrence while
        # GROUPING() keeps the FIRST, shifting every bit assignment.
        mask_sql_mapping = {
            sql_groupby: 1 << i
            for i, sql_groupby in enumerate(
                reversed(list(unique(groupby_terms.values())))
            )
        }

        mask_grouping_result_indexes = defaultdict(
            list
        )  # manage "duplicated" groupby
        for result_index, groupby in enumerate(grouping_sets):
            # E.g. for GROUPING SET ((a, b), (a), ()), GROUPING(a, b) is:
            # both=0, a only=1, b only=2, none=3.
            sql_terms = {groupby_terms[groupby_spec] for groupby_spec in groupby}
            groupby_mask = sum(
                mask
                for sql_term, mask in mask_sql_mapping.items()
                # bit is 0 if the term is in this set's grouping criteria, else 1
                if sql_term not in sql_terms
            )

            mask_grouping_result_indexes[groupby_mask].append(result_index)
            if groupby_mask not in mask_grouping_mapping:
                mask_grouping_mapping[groupby_mask] = (
                    result[result_index].append,
                    itemgetter_tuple(
                        list(
                            itertools.chain(
                                (
                                    all_groupby_specs.index(groupby_spec)
                                    for groupby_spec in groupby
                                ),
                                aggregates_indexes,
                            )
                        )
                    ),
                )

        aggregates_start_index = len(all_groupby_specs) + 1
        # Transpose rows to columns for efficient, column-wise post-processing.
        columns = list(zip(*row_values, strict=False))
        # The first column is the grouping mask
        dispatch_info = map(mask_grouping_mapping.__getitem__, columns[0])
        # Post-process values column by column
        columns = [
            *map(
                self._read_group_postprocess_groupby,
                all_groupby_specs,
                columns[1:aggregates_start_index],
                strict=False,
            ),
            *map(
                self._read_group_postprocess_aggregate,
                aggregates,
                columns[aggregates_start_index:],
                strict=False,
            ),
        ]

        # result: [
        #   [(a1, b1, <aggregates>), (a2, b2, <aggregates>), ...],
        #   [(a1, <aggregates>), (a2, <aggregates>), ...],
        #   [(<aggregates>)],
        # ]
        for (append_method, extractor), *row in zip(
            dispatch_info, *columns, strict=True
        ):
            append_method(extractor(row))

        # Groupbys targeting the same column(s) share the same results.
        for duplicate_groups_indexes in mask_grouping_result_indexes.values():
            if len(duplicate_groups_indexes) < 2:
                continue
            # The first index's result is the source for all the others.
            source_result_group = result[duplicate_groups_indexes[0]]
            for duplicate_group_index in duplicate_groups_indexes[1:]:
                result[duplicate_group_index] = source_result_group[:]

        return result

    @api.model
    def _read_group(
        self,
        domain: DomainType,
        groupby: Sequence[str] = (),
        aggregates: Sequence[str] = (),
        having: DomainType = (),
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[tuple]:
        """Aggregate ``aggregates`` grouped by ``groupby`` over records in
        ``domain``.

        :param domain: :ref:`a search domain <reference/orm/domains>`; empty list
            matches all records.
        :param groupby: list of groupby descriptions. Each is a field name or
            ``'field:granularity'``. Granularities (date/datetime only) are
            ``'hour'``, ``'day'``, ``'week'``, ``'month'``, ``'quarter'``,
            ``'year'``, and integer date parts: ``'year_number'``, ``'quarter_number'``,
            ``'month_number'``, ``'iso_week_number'``, ``'day_of_year'``,
            ``'day_of_month'``, ``'day_of_week'``, ``'hour_number'``,
            ``'minute_number'``, ``'second_number'``.
        :param aggregates: list of ``'field:agg'`` specs. ``agg`` is one of the
            allow-listed aggregates in ``odoo.orm.constants.READ_GROUP_AGGREGATE``
            (``sum``, ``avg``, ``max``, ``min``, ``bool_and``, ``bool_or``,
            ``array_agg``, ``array_agg_distinct``, ``count``, ``count_distinct``,
            ``any_value``, or ``recordset`` — ``array_agg`` as a recordset), or
            ``sum_currency`` (monetary fields only).
        :param having: a domain whose "fields" are the aggregates.
        :param offset: optional number of groups to skip
        :param limit: optional max number of groups to return
        :param order: optional ``order by`` overriding the natural group order;
            see also :meth:`~.search`.
        :return: flat list of tuples ``[(groupby_1_value, ..., aggregate_1_value,
            ...), ...]``. A related groupby value is a recordset (with a correct
            prefetch set).
        :raise AccessError: if user is not allowed to access requested information
        """
        # NB: no model-level check_access here — _search below performs the
        # identical ``self.browse().check_access("read")`` (unless su).
        query = self._search(domain)
        if query.is_empty():
            # Still validate the specs and field-level read access (like
            # search_fetch does on its empty path): an unauthorized (or
            # invalid) spec must raise the same error whether or not the
            # domain matches records.
            self._check_read_group_spec_access(groupby, aggregates)
            if not groupby:
                # HAVING applies to the single implicit aggregate group even
                # without GROUP BY (see below), so the shortcut must keep or
                # drop its one row exactly like the SQL path does over zero
                # rows (SUM() over no rows is NULL, and NULL > 0 is not TRUE;
                # COUNT(*) is 0).  Reuse the SQL having machinery over a
                # known-empty source rather than re-implementing SQL's
                # three-valued comparison semantics in Python.
                if having:
                    empty_query = Query(self.env, self._table, self._table_sql)
                    empty_query.add_where(SQL("FALSE"))
                    empty_query.having = self._read_group_having(
                        list(having), empty_query
                    )
                    if not self.env.execute_query(empty_query.select(SQL("COUNT(*)"))):
                        return []
                # with no group, postgresql always returns a row
                return [
                    tuple(
                        self._read_group_empty_value(spec)
                        for spec in itertools.chain(groupby, aggregates)
                    )
                ]
            return []

        if groupby:
            # Without a groupby, PostgreSQL returns exactly one aggregate row;
            # limit/offset would wrongly slice it away (offset=1 -> []). Only
            # paginate when there are groups.
            query.limit = limit
            query.offset = offset

        groupby_terms: dict[str, SQL] = {
            spec: self._read_group_groupby(self._table, spec, query) for spec in groupby
        }
        aggregates_terms: list[SQL] = [
            self._read_group_select(spec, query) for spec in aggregates
        ]
        select_args = [
            *[groupby_terms[spec] for spec in groupby],
            *aggregates_terms,
        ]
        if groupby_terms:
            query.order = self._read_group_orderby(order, groupby_terms, query)
            query.groupby = SQL(", ").join(groupby_terms.values())
        # HAVING is valid without GROUP BY (PostgreSQL applies it to the single
        # implicit aggregate group), so honour ``having`` even when ``groupby``
        # is empty. Guarding on ``having`` preserves the no-having behaviour.
        if having:
            query.having = self._read_group_having(list(having), query)

        # row_values: [(a1, b1, c1), (a2, b2, c2), ...]
        row_values = self.env.execute_query(query.select(*select_args))

        if not row_values:
            return []

        # post-process values column by column
        column_iterator = zip(*row_values, strict=False)

        # column_result: [(a1, a2, ...), (b1, b2, ...), (c1, c2, ...)]
        column_result = []
        for spec in groupby:
            column = self._read_group_postprocess_groupby(spec, next(column_iterator))
            column_result.append(column)
        for spec in aggregates:
            column = self._read_group_postprocess_aggregate(spec, next(column_iterator))
            column_result.append(column)
        # raise (not assert) so this holds under python -O: extra columns must
        # not be silently dropped from the result.
        if next(column_iterator, None) is not None:
            raise RuntimeError(
                f"Read group returned more columns than expected for "
                f"groupby={groupby} aggregates={aggregates}"
            )

        # return [(a1, b1, c1), (a2, b2, c2), ...]
        return list(zip(*column_result, strict=False))

    @api.model
    def _read_group_empty_value(self, spec):
        """Return the empty value corresponding to the given groupby spec or aggregate spec."""
        if spec == "__count":
            return 0
        fname, chain_fnames, func = parse_read_group_spec(
            spec
        )  # func: None, a granularity, or an aggregate
        if func in ("count", "count_distinct"):
            return 0
        if func in ("array_agg", "array_agg_distinct"):
            return []
        field = self._fields[fname]
        if (not func or func == "recordset") and (field.relational or fname == "id"):
            if chain_fnames and field.type == "many2one":
                groupby_seq = f"{chain_fnames}:{func}" if func else chain_fnames
                model = self.env[field.comodel_name]
                return model._read_group_empty_value(groupby_seq)
            return (
                self.env[field.comodel_name]
                if field.relational
                else self.env[self._name]
            )
        return False

    @api.model
    def _check_read_group_spec_access(self, groupby, aggregates) -> None:
        """Validate groupby/aggregate specs and check field read access,
        without building SQL.

        Mirrors the field-level checks of :meth:`_read_group_groupby` and
        :meth:`_read_group_select`; used on the empty-query shortcut of
        :meth:`_read_group` / :meth:`_read_grouping_sets` so field-level
        :class:`~odoo.exceptions.AccessError` (and invalid-spec errors) do not
        depend on whether the domain matched records.
        """
        for spec in groupby:
            model = self
            sub_spec = spec
            while True:
                fname, seq_fnames, granularity = parse_read_group_spec(sub_spec)
                if fname not in model._fields:
                    raise ValueError(
                        f"Invalid field {fname!r} on model {model._name!r}"
                    )
                field = model._fields[fname]
                if seq_fnames and field.type != "properties":
                    if field.type != "many2one":
                        raise ValueError(
                            f"Only many2one path is accepted for the {spec!r} groupby spec"
                        )
                    model._check_spec_field_read_access(field)
                    model = model.env[field.comodel_name]
                    sub_spec = (
                        f"{seq_fnames}:{granularity}" if granularity else seq_fnames
                    )
                    continue
                model._check_spec_field_read_access(field)
                break

        for spec in aggregates:
            if spec == "__count":
                continue
            fname, property_name, func = parse_read_group_spec(spec)
            if property_name:
                raise ValueError(
                    f"Invalid {spec!r}, this dot notation is not supported"
                )
            if fname not in self._fields:
                raise ValueError(
                    f"Invalid field {fname!r} on model {self._name!r} for {spec!r}."
                )
            if not func:
                raise ValueError(f"Aggregate method is mandatory for {fname!r}")
            if func != "sum_currency" and func not in READ_GROUP_AGGREGATE:
                raise ValueError(f"Invalid aggregate method {func!r} for {spec!r}.")
            self._check_spec_field_read_access(self._fields[fname])

    def _check_spec_field_read_access(self, field) -> None:
        """Field read-access check equivalent to :meth:`_field_to_sql`, minus
        the SQL generation (so no query/joins are needed)."""
        if field.related and not field.store:
            # Mirror _traverse_related_sql: only sudoed related or inherited
            # fields are convertible to SQL; path fields are then checked on
            # the (possibly sudoed) traversed models.
            if not (self.env.su or field.compute_sudo or field.inherited):
                raise ValueError(
                    f"Cannot convert {field} to SQL because it is not a sudoed"
                    " related or inherited field"
                )
            model = self.sudo(self.env.su or field.compute_sudo)
            *path_fnames, last_fname = field.related.split(".")
            for path_fname in path_fnames:
                path_field = model._fields[path_fname]
                model._check_field_access(path_field, "read")
                model = model.env[path_field.comodel_name]
            model._check_spec_field_read_access(model._fields[last_fname])
            return
        self._check_field_access(field, "read")

    @api.model
    @api.readonly
    @api.deprecated(
        "Since 19.0, read_group is deprecated. Please use _read_group in the backend code or formatted_read_group for a complete formatted result"
    )
    def read_group(
        self,
        domain,
        fields,
        groupby,
        offset=0,
        limit=None,
        orderby=False,
        lazy=True,
    ):
        """Deprecated - records grouped by ``groupby`` fields for list view.

        :param list domain: :ref:`a search domain <reference/orm/domains>`; empty
            list matches all records.
        :param list fields: each is ``'field'`` (default aggregation),
            ``'field:agg'``, or ``'name:agg(field)'`` (aggregate returned as
            ``name``). ``agg`` is one of the allow-listed aggregates in
            ``odoo.orm.constants.READ_GROUP_AGGREGATE`` (``sum``, ``avg``,
            ``max``, ``min``, ``bool_and``, ``bool_or``, ``array_agg``,
            ``array_agg_distinct``, ``count``, ``count_distinct``,
            ``any_value``, ``recordset``) or ``sum_currency`` (monetary
            fields only).
        :param list groupby: groupby descriptions. Each is a field name, or
            ``'field:granularity'`` for date/datetime. Granularities: ``'hour'``,
            ``'day'``, ``'week'``, ``'month'``, ``'quarter'``, ``'year'``, plus
            integer date parts (``'year_number'``, ``'quarter_number'``,
            ``'month_number'``, ``'iso_week_number'``, ``'day_of_year'``,
            ``'day_of_month'``, ``'day_of_week'``, ``'hour_number'``,
            ``'minute_number'``, ``'second_number'``).
        :param int offset: optional number of groups to skip
        :param int limit: optional max number of groups to return
        :param str orderby: optional ``order by`` overriding the natural group
            order; see also :meth:`~.search` (many2one fields only for now).
        :param bool lazy: if true, group only by the first groupby and put the
            rest under the ``__context`` key; if false, group by all at once.
        :return: list of dicts (one per group), each containing the grouped
            field values plus:

                    * ``__domain``: search criteria
                    * ``__context``: dict with arguments like ``groupby``
                    * ``__range``: (date/datetime) ``{field:granularity}`` to
                        ``{"from": inclusive, "to": exclusive}`` temporal bounds
        :rtype: [{'field_name_1': value, ...}, ...]
        :raise AccessError: if user is not allowed to access requested information
        """
        groupby = [groupby] if isinstance(groupby, str) else groupby
        lazy_groupby = groupby[:1] if lazy else groupby

        # Compatibility layer mapping the old API onto _read_group:
        # - default granularity 'month' for date/datetime groupby
        # - `fields` -> _read_group aggregates specs
        # - order -> _read_group order spec

        annotated_groupby = {}  # {result name: explicit groupby spec}
        for group_spec in lazy_groupby:
            field_name, property_name, granularity = parse_read_group_spec(group_spec)
            if field_name not in self._fields:
                raise ValueError(
                    f"Invalid field {field_name!r} on model {self._name!r}"
                )
            field = self._fields[field_name]
            if property_name and field.type != "properties":
                raise ValueError(
                    f"Property name {property_name!r} has to be used on a property field."
                )
            if field.type in ("date", "datetime"):
                annotated_groupby[group_spec] = f"{field_name}:{granularity or 'month'}"
            else:
                annotated_groupby[group_spec] = group_spec

        annotated_aggregates = {  # {result name: explicit aggregate spec}
            (
                f"{lazy_groupby[0].split(':')[0]}_count"
                if lazy and len(lazy_groupby) == 1
                else "__count"
            ): "__count",
        }
        for field_spec in fields:
            if field_spec == "__count":
                continue
            match = regex_field_agg.match(field_spec)
            if not match:
                raise ValueError(f"Invalid field specification {field_spec!r}.")
            name, func, fname = match.groups()

            if fname:  # spec like "field_min:min(field)"
                annotated_aggregates[name] = f"{fname}:{func}"
                continue
            if func:  # spec like "field:min"
                annotated_aggregates[name] = f"{name}:{func}"
                continue

            if name not in self._fields:
                raise ValueError(f"Invalid field {name!r} on model {self._name!r}")
            field = self._fields[name]
            if (
                field.base_field.store
                and field.base_field.column_type
                and field.aggregator
                and field_spec not in annotated_groupby
            ):
                annotated_aggregates[name] = f"{name}:{field.aggregator}"

        if orderby:
            new_terms = []
            for order_term in orderby.split(","):
                order_term = order_term.strip()
                for key_name, annotated in itertools.chain(
                    reversed(annotated_groupby.items()),
                    annotated_aggregates.items(),
                ):
                    key_name = key_name.split(":")[0]
                    if order_term.startswith(f"{key_name} ") or key_name == order_term:
                        # replace only the leading field token, preserving any
                        # trailing direction/nulls clause (a blanket str.replace
                        # could rewrite a later occurrence of the field name)
                        order_term = annotated + order_term[len(key_name) :]
                        break
                new_terms.append(order_term)
            orderby = ",".join(new_terms)
        else:
            orderby = ",".join(annotated_groupby.values())

        domain = Domain(domain)
        rows = self._read_group(
            domain,
            annotated_groupby.values(),
            annotated_aggregates.values(),
            offset=offset,
            limit=limit,
            order=orderby,
        )
        rows_dict = [
            dict(
                zip(
                    itertools.chain(annotated_groupby, annotated_aggregates),
                    row,
                    strict=False,
                )
            )
            for row in rows
        ]

        fill_temporal = self.env.context.get("fill_temporal")
        # NB: lazy_groupby is required in BOTH disjuncts — filling needs a
        # groupby to fill along; with groupby=[] and a dict fill_temporal, the
        # old guard crashed in _read_group_fill_temporal (groupby[0]).
        if lazy_groupby and (
            (rows_dict and fill_temporal) or isinstance(fill_temporal, dict)
        ):
            # fill_temporal = {} means True; even an empty dict may want empty
            # columns, so apply the fill logic.
            if not isinstance(fill_temporal, dict):
                fill_temporal = {}
            else:
                # fill_temporal comes from the (RPC-reachable) context: keep
                # only the keys _read_group_fill_temporal accepts as options
                # (its defaulted parameters), ignoring unknown keys instead of
                # crashing with TypeError on **-unpacking.
                known_keys = {
                    name
                    for name, param in inspect.signature(
                        self._read_group_fill_temporal
                    ).parameters.items()
                    if param.default is not inspect.Parameter.empty
                }
                fill_temporal = {
                    key: value
                    for key, value in fill_temporal.items()
                    if key in known_keys
                }
            # Filling date gaps may produce more rows than ``limit``; in practice
            # only chart views use this and they never set a limit.
            rows_dict = self._read_group_fill_temporal(
                rows_dict,
                lazy_groupby,
                annotated_aggregates,
                **fill_temporal,
            )

        if lazy_groupby and lazy:
            # read_group only fills in lazy mode (the default); eager mode would
            # need _read_group_fill_results reimplemented. Filling may exceed
            # ``limit``, but fill views (kanban, chart) don't set one.
            rows_dict = self._read_group_fill_results(
                domain,
                lazy_groupby[0],
                annotated_aggregates,
                rows_dict,
                read_group_order=orderby,
            )

        for row in rows_dict:
            row["__domain"] = domain
            if len(lazy_groupby) < len(groupby):
                row["__context"] = {"group_by": groupby[len(lazy_groupby) :]}

        self._read_group_format_result(rows_dict, lazy_groupby)

        return rows_dict
