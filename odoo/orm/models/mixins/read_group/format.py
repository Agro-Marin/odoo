import datetime
import typing

import babel
import babel.dates

from odoo.libs.datetime import all_timezones, utc
from odoo.libs.datetime import timezone as get_timezone
from odoo.tools import (
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_DATETIME_FORMAT,
    date_utils,
    get_lang,
    unique,
)

from ...._recordset import is_recordset
from ....constants import (
    READ_GROUP_DISPLAY_FORMAT,
    READ_GROUP_NUMBER_GRANULARITY,
    READ_GROUP_TIME_GRANULARITY,
)
from ....domain import Domain
from ....parsing import parse_read_group_spec
from ._empty import _ReadGroupEmptyMixin

if typing.TYPE_CHECKING:
    from collections.abc import Generator


class _ReadGroupFormatMixin(_ReadGroupEmptyMixin):
    __slots__ = ()

    def _read_group_postprocess_groupby(
        self, groupby_spec: str, raw_values: list
    ) -> Generator:
        empty_value = self._read_group_empty_value(groupby_spec)

        fname, chain_fnames, granularity = parse_read_group_spec(groupby_spec)
        field = self._fields[fname]

        if field.relational or fname == "id":
            if chain_fnames and field.relational:
                groupby_seq = (
                    f"{chain_fnames}:{granularity}" if granularity else chain_fnames
                )
                model = self.env[field.comodel_name]
                return model._read_group_postprocess_groupby(groupby_seq, raw_values)

            registry = self.env.registry
            Model = (
                registry[field.comodel_name]
                if field.relational
                else registry[self._name]
            )
            prefetch_ids = tuple(raw_value for raw_value in raw_values if raw_value)

            def recordset(value):
                return Model(self.env, (value,), prefetch_ids) if value else empty_value

            return (recordset(value) for value in raw_values)

        return ((value if value is not None else empty_value) for value in raw_values)

    def _read_group_postprocess_aggregate(
        self, aggregate_spec: str, raw_values: list
    ) -> Generator:
        empty_value = self._read_group_empty_value(aggregate_spec)

        if aggregate_spec == "__count":
            return (
                (value if value is not None else empty_value) for value in raw_values
            )

        fname, __, func = parse_read_group_spec(aggregate_spec)
        if func == "recordset":
            field = self._fields[fname]
            registry = self.env.registry
            Model = (
                registry[field.comodel_name]
                if field.relational
                else registry[self._name]
            )
            prefetch_ids = tuple(
                unique(
                    id_
                    for array_values in raw_values
                    if array_values
                    for id_ in array_values
                    if id_
                )
            )

            def recordset(value):
                if not value:
                    return empty_value
                ids = tuple(unique(id_ for id_ in value if id_))
                return Model(self.env, ids, prefetch_ids)

            return (recordset(value) for value in raw_values)

        return ((value if value is not None else empty_value) for value in raw_values)

    def _read_group_format_result(
        self, rows_dict: list[dict], lazy_groupby: list[str]
    ) -> None:
        for group in lazy_groupby:
            field_name = group.split(":")[0].split(".")[0]
            field = self._fields[field_name]

            if field.type in ("date", "datetime"):
                granularity = group.split(":")[1] if ":" in group else "month"
                if granularity in READ_GROUP_TIME_GRANULARITY:
                    locale = get_lang(self.env).code
                    fmt = (
                        DEFAULT_SERVER_DATETIME_FORMAT
                        if field.type == "datetime"
                        else DEFAULT_SERVER_DATE_FORMAT
                    )
                    interval = READ_GROUP_TIME_GRANULARITY[granularity]
            elif field.type == "properties":
                self._read_group_format_result_properties(rows_dict, group)
                continue

            for row in rows_dict:
                value = row[group]

                if is_recordset(value):
                    row[group] = (
                        (value.id, value.sudo().display_name) if value else False
                    )
                    value = value.id

                if not value and field.type == "many2many":
                    additional_domain = [(field_name, "not any", [])]
                else:
                    additional_domain = [(field_name, "=", value)]

                if field.type in ("date", "datetime"):
                    if value and isinstance(value, (datetime.date, datetime.datetime)):
                        range_start = value
                        range_end = value + interval
                        if field.type == "datetime":
                            tzinfo = None
                            if self.env.context.get("tz") in all_timezones():
                                tzinfo = get_timezone(self.env.context["tz"])
                                range_start = range_start.replace(
                                    tzinfo=tzinfo
                                ).astimezone(utc)
                                range_end = range_end.replace(tzinfo=tzinfo).astimezone(
                                    utc
                                )

                            label = babel.dates.format_datetime(
                                range_start,
                                format=READ_GROUP_DISPLAY_FORMAT[granularity],
                                tzinfo=tzinfo,
                                locale=locale,
                            )
                        else:
                            label = babel.dates.format_date(
                                value,
                                format=READ_GROUP_DISPLAY_FORMAT[granularity],
                                locale=locale,
                            )
                        if granularity == "week":
                            year, week = date_utils.weeknumber(
                                babel.Locale.parse(locale),
                                value,
                            )
                            label = f"W{week} {year:04}"

                        range_start = range_start.strftime(fmt)
                        range_end = range_end.strftime(fmt)
                        row[group] = label
                        row.setdefault("__range", {})[group] = {
                            "from": range_start,
                            "to": range_end,
                        }
                        additional_domain = [
                            "&",
                            (field_name, ">=", range_start),
                            (field_name, "<", range_end),
                        ]
                    elif (
                        value is not None
                        and granularity in READ_GROUP_NUMBER_GRANULARITY
                    ):
                        additional_domain = [
                            (f"{field_name}.{granularity}", "=", value)
                        ]
                    elif not value:
                        row.setdefault("__range", {})[group] = False

                row["__domain"] &= Domain(additional_domain)
        for row in rows_dict:
            row["__domain"] = list(row["__domain"])

    def _read_group_format_result_properties(self, rows_dict, group):
        if "." not in group:
            msg = "You must choose the property you want to group by."
            raise ValueError(msg)
        fullname, __, func = group.partition(":")

        definition = self.get_property_definition(fullname)
        property_type = definition.get("type")

        if property_type == "selection":
            options = definition.get("selection") or []
            options = tuple(option[0] for option in options)
            for row in rows_dict:
                if not row[fullname]:
                    additional_domain = Domain(fullname, "=", False) | Domain(
                        fullname, "not in", options
                    )
                else:
                    additional_domain = Domain(fullname, "=", row[fullname])

                row["__domain"] &= additional_domain

        elif property_type == "many2one":
            comodel = self.env[definition.get("comodel")]
            prefetch_ids = all_groups = tuple(
                row[fullname] for row in rows_dict if row[fullname]
            )
            for row in rows_dict:
                if not row[fullname]:
                    additional_domain = Domain(fullname, "=", False) | Domain(
                        fullname, "not in", all_groups
                    )
                else:
                    additional_domain = Domain(fullname, "=", row[fullname])
                    record = comodel.browse(row[fullname]).with_prefetch(prefetch_ids)
                    row[fullname] = (row[fullname], record.display_name)

                row["__domain"] &= additional_domain

        elif property_type == "many2many":
            comodel = self.env[definition.get("comodel")]
            prefetch_ids = all_groups = tuple(
                row[fullname] for row in rows_dict if row[fullname]
            )
            for row in rows_dict:
                if not row[fullname]:
                    if all_groups:
                        additional_domain = Domain(fullname, "=", False) | Domain.AND(
                            [(fullname, "not in", group)] for group in all_groups
                        )
                    else:
                        additional_domain = Domain.TRUE
                else:
                    additional_domain = Domain(fullname, "in", row[fullname])
                    record = comodel.browse(row[fullname]).with_prefetch(prefetch_ids)
                    row[fullname] = (row[fullname], record.display_name)

                row["__domain"] &= additional_domain

        elif property_type == "tags":
            tags = definition.get("tags") or []
            tags = {tag[0]: tag for tag in tags}
            for row in rows_dict:
                if not row[fullname]:
                    if tags:
                        additional_domain = Domain(fullname, "=", False) | Domain.AND(
                            [(fullname, "not in", tag)] for tag in tags
                        )
                    else:
                        additional_domain = Domain.TRUE
                else:
                    additional_domain = Domain(fullname, "in", row[fullname])
                    row[fullname] = tags.get(row[fullname])

                row["__domain"] &= additional_domain

        elif property_type in ("date", "datetime"):
            for row in rows_dict:
                if not row[group]:
                    row[group] = False
                    row["__domain"] &= Domain(fullname, "=", False)
                    row.setdefault("__range", {})[group] = False
                    continue

                db_format = (
                    "%Y-%m-%d" if property_type == "date" else "%Y-%m-%d %H:%M:%S"
                )

                if func == "week":
                    start = row[group].strftime(db_format)
                    end = (row[group] + datetime.timedelta(days=7)).strftime(db_format)
                else:
                    start = (date_utils.start_of(row[group], func)).strftime(db_format)
                    end = (
                        date_utils.end_of(row[group], func)
                        + datetime.timedelta(minutes=1)
                    ).strftime(db_format)

                row["__domain"] &= Domain(fullname, ">=", start) & Domain(
                    fullname, "<", end
                )
                row.setdefault("__range", {})[group] = {"from": start, "to": end}
                row[group] = babel.dates.format_date(
                    row[group],
                    format=READ_GROUP_DISPLAY_FORMAT[func],
                    locale=get_lang(self.env).code,
                )
        else:
            for row in rows_dict:
                row["__domain"] &= Domain(fullname, "=", row[fullname])
