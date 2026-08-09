import collections
import datetime

from odoo.tools import date_utils, get_lang

from .... import decorators as api
from ...._typing import (
    DomainType,
    ModelType,
)
from ....constants import READ_GROUP_TIME_GRANULARITY
from ....fields.temporal import Date, Datetime
from ._empty import _ReadGroupEmptyMixin


class _ReadGroupFillMixin(_ReadGroupEmptyMixin):
    __slots__ = ()

    @api.model
    def _read_group_expand_full(
        self, groups: ModelType, domain: DomainType
    ) -> ModelType:
        return groups.search([])

    @api.model
    def _read_group_fill_results(
        self,
        domain: DomainType,
        groupby: str,
        annotated_aggregates: dict,
        read_group_result: list[dict],
        read_group_order: str | None = None,
    ) -> list[dict]:
        field_name = groupby.split(".", maxsplit=1)[0].split(":", maxsplit=1)[0]
        field = self._fields[field_name]
        if not field.group_expand:
            return read_group_result
        if "." in groupby.split(":", maxsplit=1)[0] and field.relational:
            raise ValueError(
                f"_read_group_fill_results does not support a relational path: "
                f"{groupby!r} groups by the leaf field while {field} carries the "
                f"group_expand. Expand on the leaf's model instead."
            )

        group_expand = field.group_expand
        if isinstance(group_expand, str):
            group_expand = getattr(self.env.registry[self._name], group_expand)
        if not callable(group_expand):
            raise TypeError(
                f"group_expand of {field} must be callable or a method name, "
                f"got {group_expand!r}"
            )

        values = [line[groupby] for line in read_group_result if line[groupby]]

        if field.relational:
            groups = self.env[field.comodel_name].browse(value.id for value in values)
            values = group_expand(self, groups, domain).sudo()
            if read_group_order == groupby + " desc":
                values = values.browse(reversed(values._ids))

            def value2key(value):
                return value and value.id

        else:
            values = group_expand(self, values, domain)
            if read_group_order == groupby + " desc":
                values.reverse()

            def value2key(value):
                return value

        read_group_result_as_dict = {}
        for line in read_group_result:
            read_group_result_as_dict[value2key(line[groupby])] = line

        empty_item = {
            name: self._read_group_empty_value(spec)
            for name, spec in annotated_aggregates.items()
        }

        result = {}
        for value in values:
            key = value2key(value)
            if key in read_group_result_as_dict:
                result[key] = read_group_result_as_dict.pop(key)
            else:
                result[key] = dict(empty_item, **{groupby: value})

        for line in read_group_result_as_dict.values():
            key = value2key(line[groupby])
            result[key] = line

        if field.relational and groups._fold_name in groups._fields:
            fold = {
                group.id: group[groups._fold_name]
                for group in groups.browse(key for key in result if key)
            }
            for key, line in result.items():
                line["__fold"] = fold.get(key, False)

        return list(result.values())

    def _read_group_fill_temporal_bound(self, field, granularity, days_offset, bound):
        value = (Datetime.to_datetime if field.type == "datetime" else Date.to_date)(
            bound
        )
        if granularity == "hour":
            value = value.replace(minute=0, second=0, microsecond=0)
        else:
            value = date_utils.start_of(value, granularity)
        return value - datetime.timedelta(days=days_offset)

    @api.model
    def _read_group_fill_temporal(
        self,
        data: list[dict],
        groupby: list[str],
        annotated_aggregates: dict,
        fill_from: str | bool = False,
        fill_to: str | bool = False,
        min_groups: int | bool = False,
    ) -> list[dict]:
        first_group = groupby[0]
        field_name = first_group.split(":")[0].split(".")[0]
        field = self._fields[field_name]
        if not field.is_temporal and not (
            field.type == "properties" and ":" in first_group
        ):
            return data

        granularity = first_group.split(":")[1] if ":" in first_group else "month"
        if granularity not in READ_GROUP_TIME_GRANULARITY:
            return data

        days_offset = 0
        if granularity == "week":
            first_week_day = int(get_lang(self.env).week_start) - 1
            days_offset = first_week_day and 7 - first_week_day
        interval = READ_GROUP_TIME_GRANULARITY[granularity]

        existing = sorted(d[first_group] for d in data if d[first_group]) or [None]
        existing_from, existing_to = existing[0], existing[-1]

        if fill_from:
            fill_from = self._read_group_fill_temporal_bound(
                field, granularity, days_offset, fill_from
            )
        elif existing_from:
            fill_from = existing_from
        if fill_to:
            fill_to = self._read_group_fill_temporal_bound(
                field, granularity, days_offset, fill_to
            )
        elif existing_to:
            fill_to = existing_to

        if not fill_to and fill_from:
            fill_to = fill_from
        if not fill_from and fill_to:
            fill_from = fill_to
        if not fill_from and not fill_to:
            return data

        if min_groups > 0:
            fill_to = max(fill_to, fill_from + (min_groups - 1) * interval)

        if fill_to < fill_from:
            return data

        required_dates = date_utils.date_range(fill_from, fill_to, interval)

        if existing[0] is None:
            existing = list(required_dates)
        else:
            existing = sorted(set().union(existing, required_dates))

        empty_item = {
            name: self._read_group_empty_value(spec)
            for name, spec in annotated_aggregates.items()
        }
        for group in groupby[1:]:
            empty_item[group] = self._read_group_empty_value(group)

        grouped_data = collections.defaultdict(list)
        for d in data:
            grouped_data[d[first_group]].append(d)

        result = []
        for dt in existing:
            result.extend(grouped_data[dt] or [dict(empty_item, **{first_group: dt})])

        if False in grouped_data:
            result.extend(grouped_data[False])

        return result
