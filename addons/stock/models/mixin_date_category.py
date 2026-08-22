from datetime import UTC, timedelta

from odoo import api, fields, models
from odoo.fields import Domain


class MixinDateCategory(models.AbstractModel):
    _name = "mixin.date.category"
    _description = "Relative Day Category"

    _date_category_field = None

    date_category = fields.Selection(
        selection=[
            ("before", "Before"),
            ("yesterday", "Yesterday"),
            ("today", "Today"),
            ("day_1", "Tomorrow"),
            ("day_2", "The day after tomorrow"),
            ("after", "After"),
        ],
        string="Date Category",
        store=False,
        readonly=True,
        search="_search_date_category",
    )

    def _search_date_category(self, operator, value):
        if operator != "in":
            return NotImplemented
        if not self._date_category_field:
            raise NotImplementedError(
                f"{self._name} inherits date.category.mixin without setting "
                f"_date_category_field, so there is no column to bucket."
            )
        return Domain.OR(
            domain
            for item in value
            if (domain := self.date_category_to_domain(self._date_category_field, item))
        )

    @api.model
    def _date_category_boundaries(self):
        start_today = fields.Datetime.context_timestamp(
            self.env.user,
            fields.Datetime.now(),
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "yesterday": start_today + timedelta(days=-1),
            "today": start_today,
            "day_1": start_today + timedelta(days=1),
            "day_2": start_today + timedelta(days=2),
            "day_3": start_today + timedelta(days=3),
        }

    @api.model
    def calculate_date_category(self, value):
        if not value:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        bound = self._date_category_boundaries()
        if value < bound["yesterday"]:
            return "before"
        if value < bound["today"]:
            return "yesterday"
        if value < bound["day_1"]:
            return "today"
        if value < bound["day_2"]:
            return "day_1"
        if value < bound["day_3"]:
            return "day_2"
        return "after"

    @api.model
    def date_category_to_domain(self, field_name, date_category):
        bound = {
            key: value.astimezone(UTC).replace(tzinfo=None)
            for key, value in self._date_category_boundaries().items()
        }
        date_category_to_search_domain = {
            "before": [(field_name, "<", bound["yesterday"])],
            "yesterday": [
                (field_name, ">=", bound["yesterday"]),
                (field_name, "<", bound["today"]),
            ],
            "today": [
                (field_name, ">=", bound["today"]),
                (field_name, "<", bound["day_1"]),
            ],
            "day_1": [
                (field_name, ">=", bound["day_1"]),
                (field_name, "<", bound["day_2"]),
            ],
            "day_2": [
                (field_name, ">=", bound["day_2"]),
                (field_name, "<", bound["day_3"]),
            ],
            "after": [(field_name, ">=", bound["day_3"])],
        }
        return date_category_to_search_domain.get(date_category)
