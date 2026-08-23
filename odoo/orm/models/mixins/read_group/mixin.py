import annotationlib
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
    __slots__ = ()

    @api.model
    def _read_grouping_sets(
        self,
        domain: DomainType,
        grouping_sets: Sequence[Sequence[str]],
        aggregates: Sequence[str] = (),
        order: str | None = None,
    ) -> list[list[tuple]]:
        if not grouping_sets:
            msg = "The 'grouping_sets' parameter cannot be empty."
            raise ValueError(msg)

        query = self._search(domain)
        result = [[] for __ in grouping_sets]
        if query.is_empty():
            self._check_read_group_spec_access(
                itertools.chain.from_iterable(grouping_sets), aggregates, query
            )
            return result

        all_groupby_specs = tuple(
            unique(spec for groupby in grouping_sets for spec in groupby)
        )

        many2many_groupby_specs = []
        if len(grouping_sets) > 1:
            many2many_groupby_specs.extend(
                spec
                for spec in all_groupby_specs
                if self._groupby_spec_might_duplicate_rows(self, spec)
            )

        if many2many_groupby_specs and any(
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
        ):
            m2m_combinaisons = (
                groupby
                for i in range(len(many2many_groupby_specs), -1, -1)
                for groupby in itertools.combinations(many2many_groupby_specs, i)
            )

            grouping_sets_to_process = dict(enumerate(grouping_sets))
            batched_calls = []

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

            if grouping_sets_to_process:
                raise RuntimeError(
                    f"M2M decomposition lost grouping sets: "
                    f"{list(grouping_sets_to_process.values())}"
                )
            if len(batched_calls) > 1:
                for indexes, sub_grouping_sets in batched_calls:
                    sub_order_parts = []
                    all_sub_groupby = {
                        spec for groupby in sub_grouping_sets for spec in groupby
                    }
                    for order_part in (order or "").split(","):
                        order_part = order_part.strip()
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
                    for index, subresult in zip(indexes, sub_results, strict=True):
                        result[index] = subresult
                return result

        elif many2many_groupby_specs and "__count" in aggregates:
            aggregates = tuple(
                aggregate if aggregate != "__count" else "id:count_distinct"
                for aggregate in aggregates
            )
            if order:
                parts = []
                for part in order.split(","):
                    part = part.strip()
                    if part == "__count" or part.startswith("__count "):
                        part = "id:count_distinct" + part[len("__count") :]
                    parts.append(part)
                order = ", ".join(parts)

        groupby_terms: dict[str, SQL] = {
            spec: self._read_group_groupby(self._table, spec, query)
            for spec in all_groupby_specs
        }
        aggregates_terms: list[SQL] = [
            self._read_group_select(spec, query) for spec in aggregates
        ]
        if groupby_terms:
            grouping_select_sql = SQL(
                "GROUPING(%s)", SQL(", ").join(unique(groupby_terms.values()))
            )
        else:
            grouping_select_sql = SQL("0")

        select_args = [
            grouping_select_sql,
            *groupby_terms.values(),
            *aggregates_terms,
        ]

        query.order = self._read_group_orderby(order, groupby_terms, query)
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

        row_values = self.env.execute_query(query.select(*select_args))
        if not row_values:
            return result

        return self._read_grouping_sets_dispatch_rows(
            row_values,
            grouping_sets,
            all_groupby_specs,
            aggregates,
            groupby_terms,
            result,
        )

    def _groupby_spec_might_duplicate_rows(self, model, spec) -> bool:
        fname, property_name, __ = parse_read_group_spec(spec)
        field = model._fields[fname]
        if field.is_properties:
            definition = self.get_property_definition(f"{fname}.{property_name}")
            property_type = definition.get("type")
            return property_type in ("tags", "many2many")

        if property_name:
            if not field.is_many2one:
                raise TypeError(
                    f"Field {fname!r} on {model._name!r}: dotted groupby spec "
                    f"only supported for many2one, got {field.type!r}"
                )
            return self._groupby_spec_might_duplicate_rows(
                self.env[field.comodel_name], property_name
            )

        return field.is_many2many

    def _read_grouping_sets_dispatch_rows(
        self,
        row_values: list[tuple],
        grouping_sets: Sequence[Sequence[str]],
        all_groupby_specs: Sequence[str],
        aggregates: Sequence[str],
        groupby_terms: dict[str, SQL],
        result: list[list[tuple]],
    ) -> list[list[tuple]]:
        aggregates_indexes = tuple(
            range(len(all_groupby_specs), len(all_groupby_specs) + len(aggregates))
        )

        mask_grouping_mapping = {}

        mask_sql_mapping = {
            sql_groupby: 1 << i
            for i, sql_groupby in enumerate(
                reversed(list(unique(groupby_terms.values())))
            )
        }

        mask_grouping_result_indexes = defaultdict(list)
        for result_index, groupby in enumerate(grouping_sets):
            sql_terms = {groupby_terms[groupby_spec] for groupby_spec in groupby}
            groupby_mask = sum(
                mask
                for sql_term, mask in mask_sql_mapping.items()
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
        columns = list(zip(*row_values, strict=False))
        dispatch_info = map(mask_grouping_mapping.__getitem__, columns[0])
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

        for (append_method, extractor), *row in zip(
            dispatch_info, *columns, strict=True
        ):
            append_method(extractor(row))

        for duplicate_groups_indexes in mask_grouping_result_indexes.values():
            if len(duplicate_groups_indexes) < 2:
                continue
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
        query = self._search(domain)
        if query.is_empty():
            self._check_read_group_spec_access(groupby, aggregates, query)
            if not groupby:
                if having:
                    empty_query = Query(self.env, self._table, self._table_sql)
                    empty_query.add_where(SQL("FALSE"))
                    empty_query.having = self._read_group_having(
                        list(having), empty_query
                    )
                    if not self.env.execute_query(empty_query.select(SQL("COUNT(*)"))):
                        return []
                return [
                    tuple(
                        self._read_group_empty_value(spec)
                        for spec in itertools.chain(groupby, aggregates)
                    )
                ]
            return []

        if groupby:
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
        if having:
            query.having = self._read_group_having(list(having), query)

        row_values = self.env.execute_query(query.select(*select_args))

        if not row_values:
            return []

        column_iterator = zip(*row_values, strict=False)

        column_result = []
        for spec in groupby:
            column = self._read_group_postprocess_groupby(spec, next(column_iterator))
            column_result.append(column)
        for spec in aggregates:
            column = self._read_group_postprocess_aggregate(spec, next(column_iterator))
            column_result.append(column)
        if next(column_iterator, None) is not None:
            raise RuntimeError(
                f"Read group returned more columns than expected for "
                f"groupby={groupby} aggregates={aggregates}"
            )

        return list(zip(*column_result, strict=False))

    @api.model
    def _check_read_group_spec_access(self, groupby, aggregates, query) -> None:
        for spec in groupby:
            model = self
            sub_spec = spec
            while True:
                fname, seq_fnames, granularity = parse_read_group_spec(sub_spec)
                if fname not in model._fields:
                    model._read_group_groupby(model._table, sub_spec, query)
                    break
                field = model._fields[fname]
                if seq_fnames and not field.is_properties:
                    if not field.is_many2one:
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
        if field.related and not field.store:
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
        groupby = [groupby] if isinstance(groupby, str) else groupby
        lazy_groupby = groupby[:1] if lazy else groupby

        annotated_groupby = {}
        for group_spec in lazy_groupby:
            field_name, property_name, granularity = parse_read_group_spec(group_spec)
            if field_name not in self._fields:
                raise ValueError(
                    f"Invalid field {field_name!r} on model {self._name!r}"
                )
            field = self._fields[field_name]
            if property_name and not field.is_properties:
                raise ValueError(
                    f"Property name {property_name!r} has to be used on a property field."
                )
            if field.is_temporal:
                annotated_groupby[group_spec] = f"{field_name}:{granularity or 'month'}"
            else:
                annotated_groupby[group_spec] = group_spec

        annotated_aggregates = {
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

            if fname:
                annotated_aggregates[name] = f"{fname}:{func}"
                continue
            if func:
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
        if lazy_groupby and (
            (rows_dict and fill_temporal) or isinstance(fill_temporal, dict)
        ):
            if not isinstance(fill_temporal, dict):
                fill_temporal = {}
            else:
                known_keys = {
                    name
                    for name, param in inspect.signature(
                        self._read_group_fill_temporal,
                        annotation_format=annotationlib.Format.FORWARDREF,
                    ).parameters.items()
                    if param.default is not inspect.Parameter.empty
                }
                fill_temporal = {
                    key: value
                    for key, value in fill_temporal.items()
                    if key in known_keys
                }
            rows_dict = self._read_group_fill_temporal(
                rows_dict,
                lazy_groupby,
                annotated_aggregates,
                **fill_temporal,
            )

        if lazy_groupby and lazy:
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
