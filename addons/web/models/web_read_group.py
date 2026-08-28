from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Any

from odoo import api, models
from odoo.api import DomainType
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.models import regex_order
from odoo.tools import SQL, unique
from odoo.tools.cache_version import versioned

from .web_read_group_helpers import AND

MAX_NUMBER_OPENED_GROUPS = 10

MAX_NUMBER_RESTORED_GROUPS = 200


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    @versioned
    def web_read_group(
        self,
        domain: DomainType,
        groupby: list[str] | tuple[str, ...],
        aggregates: Sequence[str] = (),
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
        *,
        auto_unfold: bool = False,
        opening_info: list[dict] | None = None,
        unfold_read_specification: dict[str, dict] | None = None,
        unfold_read_default_limit: (int | None) = 80,
        groupby_read_specification: dict[str, dict] | None = None,
    ) -> dict[str, int | list]:
        if not isinstance(groupby, (list, tuple)) or not groupby:
            msg = "groupby must be a non-empty list or tuple"
            raise ValueError(msg)

        if (limit or offset) and "fill_temporal" in self.env.context:
            self = self.with_context(
                {k: v for k, v in self.env.context.items() if k != "fill_temporal"}
            )

        aggregates = list(aggregates)
        if "__count" not in aggregates:
            aggregates.append("__count")
        domain = Domain(domain).optimize(self)

        dict_order = self._web_read_group_get_order(order)

        first_groupby = [groupby[0]]
        read_group_order = self._get_read_group_order(
            dict_order, first_groupby, aggregates
        )
        groups, length = self._get_formatted_read_group_with_length(
            domain,
            first_groupby,
            aggregates,
            offset=offset,
            limit=limit,
            order=read_group_order,
        )

        records_opening_info: list[dict[str, Any]] = []

        self._open_groups(
            records_opening_info=records_opening_info,
            groups=groups,
            domain=domain,
            groupby=groupby,
            aggregates=aggregates,
            dict_order=dict_order,
            auto_unfold=auto_unfold,
            opening_info=opening_info,
            unfold_read_default_limit=unfold_read_default_limit,
            parent_opening_info=opening_info,
            parent_group_domain=Domain.TRUE,
        )

        if records_opening_info:
            self._web_read_group_update_records(
                records_opening_info,
                domain,
                groupby,
                dict_order,
                unfold_read_specification,
            )

        self._add_groupby_values(groupby_read_specification, groupby, groups)

        return {
            "groups": groups,
            "length": length,
        }

    def _get_records_opened_groups(
        self,
        records_opening_info: list[dict[str, Any]],
        domain: Domain,
        order_searches: str,
    ) -> list[Any]:
        to_fetch = [
            (index, sub_search)
            for index, sub_search in enumerate(records_opening_info)
            if sub_search["group"]["__count"]
        ]
        result: list[Any] = [self.browse()] * len(records_opening_info)
        if not to_fetch:
            return result
        if len(to_fetch) == 1:
            index, sub_search = to_fetch[0]
            result[index] = self.search(
                domain & sub_search["domain"],
                order=order_searches,
                limit=sub_search["limit"],
                offset=sub_search["offset"],
            )
            return result

        ids_by_index: dict[int, list[int]] = {}
        for chunk in self._chunk_opened_groups(to_fetch):
            parts = []
            for index, sub_search in chunk:
                query = self._search(
                    domain & sub_search["domain"],
                    order=order_searches,
                    limit=sub_search["limit"],
                    offset=sub_search["offset"],
                )
                if query.is_empty():
                    continue
                parts.append(
                    SQL(
                        "(SELECT %s AS __gidx,"
                        " ROW_NUMBER() OVER () AS __rn,"
                        " __g.id AS __id FROM (%s) AS __g)",
                        index,
                        query.select(),
                    )
                )
            if not parts:
                continue
            rows = self.env.execute_query(
                SQL(
                    "SELECT __gidx, __id FROM (%s) AS __u ORDER BY __gidx, __rn",
                    SQL(" UNION ALL ").join(parts),
                )
            )
            for group_index, record_id in rows:
                ids_by_index.setdefault(group_index, []).append(record_id)

        for index, record_ids in ids_by_index.items():
            result[index] = self.browse(record_ids)
        return result

    _OPENED_GROUPS_SQL_CHUNK = 50

    def _chunk_opened_groups(self, to_fetch: list) -> Iterator[list]:
        size = self._OPENED_GROUPS_SQL_CHUNK
        for start in range(0, len(to_fetch), size):
            yield to_fetch[start : start + size]

    def _get_formatted_read_group_with_length(
        self, domain, groupby, aggregates, offset=0, limit=None, order=None
    ):
        groups = self.formatted_read_group(
            domain, groupby, aggregates, offset=offset, limit=limit, order=order
        )

        if not groups:
            length = 0
        elif limit and len(groups) == limit:
            length = max(self._read_group_count(domain, groupby), len(groups) + offset)
        else:
            length = len(groups) + offset

        return groups, length

    def _read_group_count(self, domain, groupby):
        self.browse().check_access("read")
        query = self._search(domain)
        if query.is_empty():
            return 0
        if not groupby:
            return 1
        groupby_terms = {
            spec: self._read_group_groupby(self._table, spec, query) for spec in groupby
        }
        query.groupby = SQL(", ").join(groupby_terms.values())
        grouped = query.select(SQL("1"))
        [(count,)] = self.env.execute_query(SQL("SELECT COUNT(*) FROM (%s) t", grouped))
        return count

    def _add_groupby_values(
        self,
        groupby_read_specification: dict[str, dict] | None,
        groupby: list[str],
        current_groups: list,
    ):
        if (
            not groupby_read_specification
            or groupby_read_specification.keys().isdisjoint(groupby)
        ):
            return

        for groupby_spec in groupby:
            if groupby_spec in groupby_read_specification:
                base_fname = groupby_spec.split(":")[0].split(".")[0]
                relational_field = self._fields[base_fname]
                if not relational_field.comodel_name:
                    msg = "Groupby read specification requires a relational field"
                    raise ValueError(msg)
                group_ids = [
                    id_label[0]
                    for group in current_groups
                    if (id_label := group[groupby_spec])
                ]
                records = self.env[relational_field.comodel_name].browse(group_ids)

                spec = groupby_read_specification[groupby_spec]
                try:
                    result_read = records.web_read(spec)
                except AccessError:
                    result_read = []
                    for record in records:
                        try:
                            result_read += record.web_read(spec)
                        except AccessError:
                            continue
                result_read_map = {values["id"]: values for values in result_read}
                for group in current_groups:
                    id_label = group[groupby_spec]
                    if not id_label:
                        group["__values"] = {"id": False}
                    elif id_label[0] in result_read_map:
                        group["__values"] = result_read_map[id_label[0]]
                    else:
                        group["__values"] = {
                            "id": id_label[0],
                            "display_name": (
                                id_label[1] if len(id_label) > 1 else None
                            ),
                        }

            current_groups = [
                subgroup
                for group in current_groups
                for subgroup in group.get("__groups", {}).get("groups", ())
            ]

    def _get_read_group_order(
        self,
        dict_order: dict[str, str],
        groupby: list[str],
        aggregates: Sequence[str],
    ) -> str:
        if not dict_order:
            return ", ".join(groupby)

        groupby = list(groupby)
        order_spec = []
        for fname, direction in dict_order.items():
            if fname == "__count":
                order_spec.append(f"{fname} {direction}")
                continue
            for group in list(groupby):
                if fname == group or group.startswith(f"{fname}:"):
                    groupby.remove(group)
                    order_spec.append(f"{group} {direction}")
                    break
            else:
                for agg_spec in aggregates:
                    if agg_spec.startswith(f"{fname}:"):
                        order_spec.append(f"{agg_spec} {direction}")
                        break
                else:
                    field = self._fields.get(fname)
                    if field and field.aggregator:
                        order_spec.append(f"{fname}:{field.aggregator} {direction}")

        return ", ".join(order_spec + groupby)

    def _web_read_group_get_order(self, order: str | None) -> dict[str, str]:
        """`order` parsed into one direction (with NULLS clause) per field path."""
        dict_order: dict[str, str] = {}
        for order_part in order.split(",") if order else ():
            order_match = regex_order.match(order_part)
            if not order_match:
                raise ValueError(f"Invalid order {order!r} for web_read_group()")
            fname_and_property = order_match["field"]
            if order_match["property"]:
                fname_and_property = f"{fname_and_property}.{order_match['property']}"
            direction = (order_match["direction"] or "ASC").upper()
            if order_match["nulls"]:
                direction = f"{direction} {order_match['nulls'].upper()}"
            dict_order[fname_and_property] = direction
        return dict_order

    def _web_read_group_update_records(
        self,
        records_opening_info: list[dict[str, Any]],
        domain: Domain,
        groupby: list[str] | tuple[str, ...],
        dict_order: dict[str, str],
        unfold_read_specification: dict[str, dict] | None,
    ) -> None:
        """Read the records of every opened group, in one batch, into `__records`."""
        if dict_order:
            order_specs = [
                f"{fname} {direction}"
                for fname, direction in dict_order.items()
                if fname not in groupby
                if fname != "__count"
            ]
            if "id" not in dict_order:
                order_specs.append("id")
        else:
            order_specs = [
                order_str
                for order_str in self._order.split(",")
                if order_str.strip().split(" ", 1)[0] not in groupby
            ]

        recordset_groups = self._get_records_opened_groups(
            records_opening_info, domain, ", ".join(order_specs)
        )

        all_records = self.browse().union(*recordset_groups)
        record_mapped = {
            values["id"]: values
            for values in all_records.web_read(unfold_read_specification or {})
        }

        for opening, records in zip(
            records_opening_info, recordset_groups, strict=True
        ):
            opening["group"]["__records"] = [
                record_mapped[record_id]
                for record_id in records._ids
                if record_id in record_mapped
            ]

    def _open_groups(
        self,
        *,
        records_opening_info: list[dict[str, Any]],
        groups: list[dict],
        domain: Domain,
        groupby: list[str],
        aggregates: list[str],
        dict_order: dict[str, str],
        auto_unfold: bool,
        opening_info: list[dict] | None,
        unfold_read_default_limit: int | None,
        parent_opening_info: list[dict] | None,
        parent_group_domain: Domain,
    ):
        ctx_max = self.env.context.get("max_number_opened_groups")
        budget = (
            MAX_NUMBER_OPENED_GROUPS if ctx_max is None else ctx_max,
            max(MAX_NUMBER_RESTORED_GROUPS, ctx_max or 0),
        )

        parent_opening_info_dict = {
            info_opening["value"]: info_opening
            for info_opening in parent_opening_info or ()
        }
        groupby_spec = groupby[0]
        field = self._fields[groupby_spec.split(":")[0].split(".")[0]]
        nb_opened_group = 0

        last_level = len(groupby) == 1
        read_group_order = None
        if not last_level:
            read_group_order = self._get_read_group_order(
                dict_order, [groupby[1]], aggregates
            )

        for group in groups:
            opening = self._get_group_opening(
                group,
                groupby_spec=groupby_spec,
                field=field,
                auto_unfold=auto_unfold,
                opening_info=opening_info,
                parent_opening_info_dict=parent_opening_info_dict,
                opened=nb_opened_group,
                budget=budget,
                unfold_read_default_limit=unfold_read_default_limit,
            )
            if opening is None:
                continue

            nb_opened_group += 1
            if last_level:
                self._open_leaf_group(
                    records_opening_info=records_opening_info,
                    group=group,
                    domain=domain,
                    aggregates=aggregates,
                    parent_group_domain=parent_group_domain,
                    opening=opening,
                )
            else:
                self._open_subgroups(
                    records_opening_info=records_opening_info,
                    group=group,
                    domain=domain,
                    groupby=groupby,
                    aggregates=aggregates,
                    dict_order=dict_order,
                    opening_info=opening_info,
                    unfold_read_default_limit=unfold_read_default_limit,
                    parent_group_domain=parent_group_domain,
                    read_group_order=read_group_order,
                    opening=opening,
                )

    def _get_group_opening(
        self,
        group: dict,
        *,
        groupby_spec: str,
        field: Any,
        auto_unfold: bool,
        opening_info: list[dict] | None,
        parent_opening_info_dict: dict,
        opened: int,
        budget: tuple[int, int],
        unfold_read_default_limit: int | None,
    ) -> dict[str, Any] | None:
        """How `group` is to be opened, or None when it stays closed.

        Consumes the group's own `__fold` marker on the way, as the caller's
        loop did: every group is asked, whether or not it ends up opened.
        """
        max_opened, max_restored = budget
        fold_info = "__fold" in group
        fold = group.pop("__fold", False)

        groupby_value = group[groupby_spec]
        raw_groupby_value = (
            groupby_value[0] if isinstance(groupby_value, tuple) else groupby_value
        )

        if opening_info and raw_groupby_value in parent_opening_info_dict:
            group_info = parent_opening_info_dict[raw_groupby_value]
            if group_info.get("folded") or opened >= max_restored:
                return None
            return {
                "limit": group_info.get("limit", unfold_read_default_limit),
                "offset": max(0, int(group_info.get("offset") or 0)),
                "progressbar_domain": group_info.get("progressbar_domain"),
                "subgroup_opening_info": group_info.get("groups"),
            }
        if (
            opened >= max_opened
            or (not auto_unfold and not fold_info)
            or fold
            or (field.relational and not group[groupby_spec])
        ):
            return None
        return {
            "limit": unfold_read_default_limit,
            "offset": 0,
            "progressbar_domain": None,
            "subgroup_opening_info": None,
        }

    def _open_leaf_group(
        self,
        *,
        records_opening_info: list[dict[str, Any]],
        group: dict,
        domain: Domain,
        aggregates: list[str],
        parent_group_domain: Domain,
        opening: dict[str, Any],
    ) -> None:
        """Record the read `group`'s own records need, at the deepest groupby."""
        records_domain = parent_group_domain & Domain(group["__extra_domain"])
        offset = opening["offset"]

        if opening["progressbar_domain"]:
            records_domain &= Domain(opening["progressbar_domain"])
            self._replace_progressbar_aggregates(
                group, aggregates, domain & records_domain
            )

        if offset and offset >= group["__count"]:
            group["__offset"] = offset = 0

        records_opening_info.append(
            {
                "domain": records_domain,
                "limit": opening["limit"],
                "offset": offset,
                "group": group,
            }
        )

    def _open_subgroups(
        self,
        *,
        records_opening_info: list[dict[str, Any]],
        group: dict,
        domain: Domain,
        groupby: list[str],
        aggregates: list[str],
        dict_order: dict[str, str],
        opening_info: list[dict] | None,
        unfold_read_default_limit: int | None,
        parent_group_domain: Domain,
        read_group_order: str | None,
        opening: dict[str, Any],
    ) -> None:
        """Read `group`'s own subgroups, and recurse into them."""
        subgroup_domain = parent_group_domain
        if group["__extra_domain"]:
            subgroup_domain &= Domain(group["__extra_domain"])
        subgroups, length = self._get_formatted_read_group_with_length(
            domain=(subgroup_domain & domain),
            groupby=[groupby[1]],
            aggregates=aggregates,
            offset=opening["offset"],
            limit=opening["limit"],
            order=read_group_order,
        )

        group["__groups"] = {
            "groups": subgroups,
            "length": length,
        }
        self._open_groups(
            records_opening_info=records_opening_info,
            groups=subgroups,
            domain=domain,
            groupby=groupby[1:],
            aggregates=aggregates,
            dict_order=dict_order,
            auto_unfold=False,
            opening_info=opening_info,
            unfold_read_default_limit=unfold_read_default_limit,
            parent_opening_info=opening["subgroup_opening_info"],
            parent_group_domain=subgroup_domain,
        )

    def _replace_progressbar_aggregates(
        self,
        group: dict,
        aggregates: Sequence[str],
        filtered_domain: Domain,
    ) -> None:
        agg_specs = [spec for spec in aggregates if spec != "__count"]
        if not agg_specs:
            return
        [filtered_group] = self.formatted_read_group(filtered_domain, (), agg_specs)
        for spec in agg_specs:
            group[spec] = filtered_group[spec]

    @api.model
    @api.readonly
    def formatted_read_grouping_sets(
        self,
        domain: DomainType,
        grouping_sets: Sequence[Sequence[str]],
        aggregates: Sequence[str] = (),
        *,
        order: str | None = None,
    ):
        grouping_sets = [tuple(groupby) for groupby in grouping_sets]
        aggregates = tuple(
            agg.replace(":recordset", ":array_agg") for agg in aggregates
        )

        if not order:
            order = ", ".join(
                unique(spec for groupby in grouping_sets for spec in groupby)
            )

        groups_list = self._read_grouping_sets(
            domain,
            grouping_sets,
            aggregates,
            order=order,
        )

        for groups_index, groupby in enumerate(grouping_sets):
            if self._web_read_group_get_field_expand(groupby):
                groups_list[groups_index] = self._web_read_group_expand(
                    domain,
                    groups_list[groups_index],
                    groupby[0],
                    aggregates,
                    order,
                )

        for groups_index, groupby in enumerate(grouping_sets):
            fill_temporal = self.env.context.get("fill_temporal")
            if groupby and (fill_temporal or isinstance(fill_temporal, dict)):
                if not isinstance(fill_temporal, dict):
                    fill_temporal = {}
                groups_list[groups_index] = self._web_read_group_fill_temporal(
                    groups_list[groups_index],
                    groupby,
                    aggregates,
                    **fill_temporal,
                )

        return [
            self._web_read_group_format(groupby, aggregates, groups)
            for groupby, groups in zip(grouping_sets, groups_list, strict=True)
        ]

    @api.model
    @api.readonly
    def formatted_read_group(
        self,
        domain: DomainType,
        groupby: Sequence[str] = (),
        aggregates: Sequence[str] = (),
        having: DomainType = (),
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict]:
        groupby = tuple(groupby)
        aggregates = tuple(
            agg.replace(":recordset", ":array_agg") for agg in aggregates
        )

        if not order:
            order = ", ".join(groupby)

        groups = self._read_group(
            domain,
            groupby,
            aggregates,
            having=having,
            offset=offset,
            limit=limit,
            order=order,
        )

        if (
            not offset
            and (not limit or len(groups) < limit)
            and self._web_read_group_get_field_expand(groupby)
        ):
            expand_groups = self._web_read_group_expand(
                domain, groups, groupby[0], aggregates, order
            )
            if not limit or len(expand_groups) <= limit:
                groups = expand_groups

        fill_temporal = self.env.context.get("fill_temporal")
        if groupby and (fill_temporal or isinstance(fill_temporal, dict)):
            if limit or offset:
                msg = "You cannot use fill_temporal with a limit or an offset"
                raise ValueError(msg)
            if not isinstance(fill_temporal, dict):
                fill_temporal = {}
            groups = self._web_read_group_fill_temporal(
                groups, groupby, aggregates, **fill_temporal
            )

        return self._web_read_group_format(groupby, aggregates, groups)

    def _web_read_group_format(
        self,
        groupby: tuple[str, ...],
        aggregates: tuple[str, ...],
        groups: list[tuple],
    ) -> list[dict]:
        result = [{"__extra_domains": []} for __ in groups]
        if not groups:
            return result
        column_iterator = zip(*groups, strict=True)

        expand_field = self._web_read_group_get_field_expand(groupby)
        for groupby_spec, values in zip(groupby, column_iterator, strict=False):
            field_path = groupby_spec.split(":")[0]
            field_name = field_path.split(".")[0]
            field = self._fields[field_name]
            is_simple = (
                "." not in field_path
                and ":" not in groupby_spec
                and field.type
                not in (
                    "many2one",
                    "many2many",
                    "date",
                    "datetime",
                    "properties",
                )
                and field_name != "id"
            )

            if is_simple:
                for value, dict_group in zip(values, result, strict=True):
                    dict_group[groupby_spec] = value
                    dict_group["__extra_domains"].append([(field_name, "=", value)])
            else:
                formatter = self._web_read_group_get_groupby_formatter(
                    groupby_spec, values
                )
                for value, dict_group in zip(values, result, strict=True):
                    dict_group[groupby_spec], additional_domain = formatter(value)
                    dict_group["__extra_domains"].append(additional_domain)

            if expand_field and expand_field.relational:
                model = self.env[expand_field.comodel_name]
                fold_name = model._fold_name
                if fold_name not in model._fields:
                    continue
                for value, dict_group in zip(values, result, strict=True):
                    dict_group["__fold"] = value.sudo()[fold_name]

        for dict_group in result:
            dict_group["__extra_domain"] = AND(dict_group.pop("__extra_domains"))

        for aggregate_spec, values in zip(aggregates, column_iterator, strict=True):
            for value, dict_group in zip(values, result, strict=True):
                dict_group[aggregate_spec] = value

        return result

    @api.model
    @api.readonly
    def read_progress_bar(self, domain, group_by, progress_bar):
        def adapt(value):
            if isinstance(value, tuple):
                return value[0]
            return value

        result = defaultdict(lambda: dict.fromkeys(progress_bar["colors"], 0))

        for group in self.formatted_read_group(
            domain,
            [group_by, progress_bar["field"]],
            ["__count"],
        ):
            field_value = group[progress_bar["field"]]
            if field_value in progress_bar["colors"]:
                group_by_value = str(adapt(group[group_by]))
                result[group_by_value][field_value] += group["__count"]

        return result
