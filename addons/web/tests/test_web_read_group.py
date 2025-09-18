"""Tests for web_read_group grouped-data operations.

Covers:
- ``max_number_opened_groups=0`` context key correctly disabling auto-open
  (bug: ``0 or DEFAULT`` short-circuit made 0 an alias for the default).
- ``_add_groupby_values`` with a granularity-decorated spec key not raising
  KeyError (bug: ``self._fields[groupby_spec]`` included the ``:month`` suffix).
"""

from odoo.tests import TransactionCase, tagged


@tagged("web_unit", "web_read_group")
class TestWebReadGroup(TransactionCase):
    """Unit tests for web_read_group and its internal helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Two companies and one person — two non-empty is_company groups.
        cls.partners = cls.env["res.partner"].create(
            [
                {"name": "WRG Test Company 1", "is_company": True},
                {"name": "WRG Test Company 2", "is_company": True},
                {"name": "WRG Test Person 1", "is_company": False},
            ]
        )
        cls.domain = [("id", "in", cls.partners.ids)]

    def test_open_groups_zero_max_disables_auto_open(self):
        """``max_number_opened_groups=0`` must prevent all groups from auto-opening.

        Before fix: ``ctx_value or MAX_NUMBER_OPENED_GROUPS`` short-circuited
        ``0`` to the default 10, so setting 0 in context had no effect.
        After fix: the ``is None`` check preserves 0 as a valid limit.
        """
        result = (
            self.env["res.partner"]
            .with_context(max_number_opened_groups=0)
            .web_read_group(
                domain=self.domain,
                groupby=["is_company"],
                aggregates=["__count"],
                auto_unfold=True,
                unfold_read_specification={"display_name": {}},
            )
        )
        for group in result["groups"]:
            self.assertNotIn(
                "__records",
                group,
                "No group should be auto-opened when max_number_opened_groups=0",
            )

    def test_open_groups_nonzero_max_allows_auto_open(self):
        """Sanity check: ``max_number_opened_groups=1`` opens at least one non-empty group."""
        result = (
            self.env["res.partner"]
            .with_context(max_number_opened_groups=1)
            .web_read_group(
                domain=self.domain,
                groupby=["is_company"],
                aggregates=["__count"],
                auto_unfold=True,
                unfold_read_specification={"display_name": {}},
            )
        )
        self.assertTrue(
            any("__records" in g for g in result["groups"]),
            "At least one group should be auto-opened when max_number_opened_groups=1",
        )

    def test_add_groupby_values_granularity_raises_value_error_not_key_error(self):
        """A granularity-decorated spec key must yield ValueError, not KeyError.

        Before fix: ``self._fields["create_date:month"]`` raised ``KeyError``
        because the field registry is keyed by bare name, not decorated spec.
        After fix: ``base_fname`` is split out first so ``self._fields["create_date"]``
        succeeds; then ``ValueError`` is raised because ``create_date`` has no
        ``comodel_name`` (it is not a relational field).
        """
        with self.assertRaises(ValueError):
            self.env["res.partner"]._add_groupby_values(
                groupby_read_specification={"create_date:month": {}},
                groupby=["create_date:month"],
                current_groups=[],
            )
