from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from odoo.fields import Domain
from odoo.libs.intervals import Intervals
from odoo.tools.date_utils import sum_intervals

if TYPE_CHECKING:
    from .resource_resource import ResourceResource

HOURS_PER_DAY = 8


def filter_domain_leaf(
    domain: Domain | list,
    field_check: Callable[[str], bool],
    field_name_mapping: dict[str, str] | None = None,
) -> Domain:
    field_name_mapping = field_name_mapping or {}

    def adapt_condition(condition, ignored):
        field_name = condition.field_expr
        if not field_check(field_name):
            return ignored
        field_name = field_name_mapping.get(field_name)
        if field_name is None:
            return condition
        return Domain(field_name, condition.operator, condition.value)

    def adapt_domain(domain: Domain, ignored) -> Domain:
        if hasattr(domain, "OPERATOR"):
            if domain.OPERATOR in ("&", "|"):
                domain = domain.apply(
                    adapt_domain(d, domain.ZERO) for d in domain.children
                )
            elif domain.OPERATOR == "!":
                domain = ~adapt_domain(~domain, ~ignored)
            else:
                msg = f"domain.OPERATOR = {domain.OPERATOR!r} unhandled"
                raise AssertionError(msg)
        else:
            domain = domain.map_conditions(
                lambda condition: adapt_condition(condition, ignored)
            )
        return ignored if domain.is_true() or domain.is_false() else domain

    domain = Domain(domain)
    if domain.is_false():
        return domain
    return adapt_domain(domain, ignored=Domain.TRUE)


@dataclass
class ResourceSchedule:
    intervals: defaultdict[int, Intervals] = field(
        default_factory=lambda: defaultdict(Intervals)
    )
    calendar_intervals: dict[int, Intervals] = field(default_factory=dict)
    hours_per_day: defaultdict[int, dict] = field(
        default_factory=lambda: defaultdict(dict)
    )
    hours_per_week: defaultdict[int, dict] = field(
        default_factory=lambda: defaultdict(dict)
    )
    flexible_ids: frozenset[int] = frozenset()

    def work_hours(
        self,
        resource: ResourceResource,
        intervals: Intervals | None = None,
        work_hours_per_day: dict[Any, float] | None = None,
    ) -> float:
        if intervals is None:
            intervals = self.intervals[resource.id]
        if resource.id in self.flexible_ids:
            return resource._get_flexible_resource_work_hours(
                intervals,
                self.hours_per_day[resource.id],
                self.hours_per_week[resource.id],
                work_hours_per_day,
            )
        hours = sum_intervals(intervals)
        if work_hours_per_day is not None:
            for start, stop, _meta in intervals:
                work_hours_per_day[start.date()] += (
                    stop - start
                ).total_seconds() / 3600
        return hours
