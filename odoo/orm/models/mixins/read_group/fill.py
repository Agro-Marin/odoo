"""Fill/expansion for read_group: empty groups, expansion, temporal gaps."""

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
from .._model_stubs import _ModelStubs


class _ReadGroupFillMixin(_ModelStubs):
    """Fill empty groups, expand groups, and fill temporal gaps."""

    __slots__ = ()

    @api.model
    def _read_group_expand_full(
        self, groups: ModelType, domain: DomainType
    ) -> ModelType:
        """Extend the group to include all target records by default."""
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
        """Fill in empty groups for all possible values of the grouped field."""
        field_name = groupby.split(".", maxsplit=1)[0].split(":", maxsplit=1)[0]
        field = self._fields[field_name]
        if not field.group_expand:
            return read_group_result

        # field.group_expand is a callable (or method name) returning the groups
        # to display, as a recordset or list of values. Used e.g. by kanban
        # views to show columns even when they hold no record.
        group_expand = field.group_expand
        if isinstance(group_expand, str):
            group_expand = getattr(self.env.registry[self._name], group_expand)
        # raise (not assert) so this holds under python -O: a non-callable
        # group_expand must fail clearly here, not opaquely at the call sites.
        if not callable(group_expand):
            raise TypeError(
                f"group_expand of {field} must be callable or a method name, "
                f"got {group_expand!r}"
            )

        # determine all groups that should be returned
        values = [line[groupby] for line in read_group_result if line[groupby]]

        if field.relational:
            # groups is a recordset; determine order on groups's model
            groups = self.env[field.comodel_name].browse(value.id for value in values)
            values = group_expand(self, groups, domain).sudo()
            if read_group_order == groupby + " desc":
                values = values.browse(reversed(values._ids))

            def value2key(value):
                return value and value.id

        else:
            # groups is a list of values
            values = group_expand(self, values, domain)
            if read_group_order == groupby + " desc":
                values.reverse()

            def value2key(value):
                return value

        # Merge current results with all groups, preserving read_group_result
        # order (for a many2one field).
        read_group_result_as_dict = {}
        for line in read_group_result:
            read_group_result_as_dict[value2key(line[groupby])] = line

        empty_item = {
            name: self._read_group_empty_value(spec)
            for name, spec in annotated_aggregates.items()
        }

        result = {}
        # fill result with the values order
        for value in values:
            key = value2key(value)
            if key in read_group_result_as_dict:
                result[key] = read_group_result_as_dict.pop(key)
            else:
                result[key] = dict(empty_item, **{groupby: value})

        for line in read_group_result_as_dict.values():
            key = value2key(line[groupby])
            result[key] = line

        # add folding information if present
        if field.relational and groups._fold_name in groups._fields:
            fold = {
                group.id: group[groups._fold_name]
                for group in groups.browse(key for key in result if key)
            }
            for key, line in result.items():
                line["__fold"] = fold.get(key, False)

        return list(result.values())

    def _read_group_fill_temporal_bound(self, field, granularity, days_offset, bound):
        """Parse and snap one ``fill_temporal`` bound to its granularity bucket.

        Shared by :meth:`_read_group_fill_temporal` and the web layer's
        ``_web_read_group_fill_temporal`` to keep bound parsing in one place.

        ``bound`` is a date/datetime string (``%Y-%m-%d`` or
        ``%Y-%m-%d %H:%M:%S``), parsed by the GROUPED FIELD's type (not the
        argument's Python type) and kept naive: group keys are naive local-time
        values (``date_trunc`` already applied the user's tz in SQL), so a
        ``date``-typed or tz-aware bound would crash the naive ``datetime``
        comparisons that follow.
        """
        value = (Datetime.to_datetime if field.type == "datetime" else Date.to_date)(
            bound
        )
        if granularity == "hour":
            # date_utils.start_of supports day-and-coarser granularities only.
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
        """Fill date/datetime 'holes' in a result set.

        For data grouped by a date field (e.g. months) and shown in a chart.
        With data only for June, September and December, plotting by default
        gives::

                                                ___
                                      ___      |   |
                                     |   | ___ |   |
                                     |___||___||___|
                                      Jun  Sep  Dec

        December immediately following September is misleading; adding explicit
        zeroes for the missing months gives::

                                                           ___
                             ___                          |   |
                            |   |           ___           |   |
                            |___| ___  ___ |___| ___  ___ |___|
                             Jun  Jul  Aug  Sep  Oct  Nov  Dec

        The context key "fill_temporal" customizes this via a dict with
        ``fill_from``, ``fill_to``, ``min_groups`` (see params below).

        Fill between bounds: ``fill_from`` and/or ``fill_to`` force at least
        that date range to be returned as contiguous groups. Groups outside the
        bounds are kept, but filling happens only between them; absent bounds
        fall back to existing groups. This yields empty groups before/after any
        group with data. Filling only between August (fill_from) and October
        (fill_to)::

                                                     ___
                                 ___                |   |
                                |   |      ___      |   |
                                |___| ___ |___| ___ |___|
                                 Jun  Aug  Sep  Oct  Dec

        June and December remain. To drop them, match ``fill_from``/``fill_to``
        with the domain, e.g. ``['&', ('date_field', '>=', 'YYYY-08-01'),
        ('date_field', '<', 'YYYY-11-01')]``::

                                         ___
                                    ___ |___| ___
                                    Aug  Sep  Oct

        Minimal filling amount: ``min_groups`` requests at least that many
        contiguous groups, counted from ``fill_from`` if set else the lowest
        existing group, and not capped by ``fill_to``. An existing group before
        ``fill_from`` does not shift the start. With neither bound and no
        existing group, nothing is returned. With min_groups = 4::

                                         ___
                                    ___ |___| ___ ___
                                    Aug  Sep  Oct Nov

        :param list data: the data containing groups
        :param list groupby: list of fields being grouped on
        :param dict annotated_aggregates: dict of "<key_name>:<aggregate specification>"
        :param str fill_from: (inclusive) start bound, as a date/datetime string
            (``%Y-%m-%d`` or ``%Y-%m-%d %H:%M:%S``)
        :param str fill_to: (inclusive) end bound, same formats as ``fill_from``
        :param int min_groups: minimal number of groups for the range (>= 1)
        :rtype: list[dict]
        :return: list
        """
        # min_groups is used by web clients (fill_temporal context key); keep.
        first_group = groupby[0]
        field_name = first_group.split(":")[0].split(".")[0]
        field = self._fields[field_name]
        if field.type not in ("date", "datetime") and not (
            field.type == "properties" and ":" in first_group
        ):
            return data

        granularity = first_group.split(":")[1] if ":" in first_group else "month"
        days_offset = 0
        if granularity == "week":
            # Week groups are locale-dependent, so filled groups must be too,
            # to avoid overlaps.
            first_week_day = int(get_lang(self.env).week_start) - 1
            days_offset = first_week_day and 7 - first_week_day
        interval = READ_GROUP_TIME_GRANULARITY[granularity]

        # Existing non-null datetimes, sorted: the bounds below assume
        # chronological order, but ``data`` follows the caller's ``orderby``,
        # which may be descending.
        existing = sorted(d[first_group] for d in data if d[first_group]) or [None]
        existing_from, existing_to = existing[0], existing[-1]

        # Resolve the bounds: explicit ones are parsed/snapped via the shared
        # helper; absent ones fall back to the existing extrema.
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
