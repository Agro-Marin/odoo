from datetime import UTC, timedelta

from odoo import api, fields, models


class DateCategoryMixin(models.AbstractModel):
    """Classify a datetime into a day bucket relative to today, and search on it.

    Nothing here is about any one model: the caller names the field, and the only
    state involved is the reading user's timezone. It lived on `stock.picking`
    because that is where the picking dashboard needed it first, which left
    `repair.order` asking `stock.picking` how to bucket its `schedule_date` and
    `mrp.production` doing the same for `date_start`. Inherit this instead.

    The six buckets are "before", "yesterday", "today", "day_1" (tomorrow),
    "day_2" and "after"; `calculate_date_category` names one for a value, and
    `date_category_to_domain` turns a name back into a domain on a given field, so
    the classification and the search can never drift apart.
    """

    _name = "date.category.mixin"
    _description = "Relative Day Category"

    @api.model
    def _date_category_boundaries(self):
        """Day boundaries (tz-aware, in the current user's timezone) used to classify a
        datetime relative to today. Returns the start of "yesterday", "today", "day_1"
        (tomorrow), "day_2" and "day_3".
        """
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
        """Classify `value` (a datetime, assumed UTC) as "before", "yesterday", "today",
        "day_1" (tomorrow), "day_2" or "after", relative to the current user's timezone.
        Returns "" if `value` is falsy.
        """
        if not value:
            return ""
        # Stored datetimes are naive UTC; `astimezone` would reinterpret a naive
        # value in the server's OS timezone, so attach UTC explicitly instead.
        # Aware values are converted by instant, matching the tz-aware boundaries.
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
        """Build a domain on `field_name` matching the given date category (one of "before",
        "yesterday", "today", "day_1", "day_2", "after"; see `calculate_date_category`).
        Returns None if `date_category` is not one of these.
        """
        # Stored datetimes are naive UTC, so express the boundaries the same way.
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
