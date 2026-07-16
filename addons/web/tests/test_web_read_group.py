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

    def test_read_progress_bar_datetime_keys_match_client_non_utc(self):
        """read_progress_bar keys must match the kanban client's group keys for
        datetime grouping under a non-UTC timezone.

        Regression: keying on raw ``_read_group`` buckets emits local-naive
        datetime strings (e.g. ``'2026-06-01 00:00:00'``) while the kanban
        client derives its lookup key from ``web_read_group`` /
        ``formatted_read_group`` (UTC, e.g. ``'2026-06-01 06:00:00'``). The
        two never matched for non-UTC users, so every progress bar rendered
        zero. ``read_progress_bar`` must therefore go through
        ``formatted_read_group`` (which produces the same keys the client uses).
        """
        model = self.env["res.partner"].with_context(tz="America/Mexico_City")
        group_by = "create_date:month"
        progress_bar = {"field": "is_company", "colors": {True: "green", False: "red"}}

        pb = model.read_progress_bar(self.domain, group_by, progress_bar)

        formatted = model.formatted_read_group(self.domain, [group_by], ["__count"])
        client_keys = {
            str(g[group_by][0] if isinstance(g[group_by], tuple) else g[group_by])
            for g in formatted
        }

        self.assertTrue(pb, "expected at least one progress-bar group")
        self.assertTrue(
            set(pb.keys()) <= client_keys,
            f"read_progress_bar keys {set(pb.keys())} must be a subset of the "
            f"client's group keys {client_keys}; a mismatch zeroes every "
            f"progress bar for non-UTC users",
        )
        # Every record must land in some bar (2 companies + 1 person).
        total = sum(sum(states.values()) for states in pb.values())
        self.assertEqual(total, len(self.partners))

    def test_web_read_group_length_counts_all_groups_when_page_full(self):
        """When the first page fills ``limit``, ``length`` must report the true
        total group count.

        Regression: the total was computed as ``limit + len(_read_group(...,
        offset=limit))``, materialising and post-processing every trailing
        group row just to count them. It is now a single ``COUNT(*)`` over the
        grouped sub-query, which must yield the same total.
        """
        Partner = self.env["res.partner"]
        partners = Partner.create([{"name": f"WRG Count {i}"} for i in range(5)])
        domain = [("id", "in", partners.ids)]
        # 5 distinct names => 5 groups; a full page of 2 hides 3 more.
        result = Partner.web_read_group(
            domain=domain, groupby=["name"], aggregates=["__count"], limit=2
        )
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["length"], 5)

    def test_read_group_count_matches_len_read_group(self):
        """``_read_group_count`` must equal ``len(_read_group(...))`` — the
        semantics it replaces — across boolean, char and relational groupbys
        (incl. an all-NULL relational group)."""
        Partner = self.env["res.partner"]
        for groupby in (["is_company"], ["name"], ["country_id"], ["parent_id"]):
            expected = len(Partner._read_group(self.domain, groupby=groupby))
            self.assertEqual(
                Partner._read_group_count(self.domain, groupby),
                expected,
                f"count mismatch for groupby={groupby}",
            )

    def test_read_group_count_edge_cases(self):
        """Empty query => 0 groups; no groupby => exactly one implicit row."""
        Partner = self.env["res.partner"]
        self.assertEqual(
            Partner._read_group_count([("id", "in", [])], ["is_company"]), 0
        )
        self.assertEqual(Partner._read_group_count(self.domain, []), 1)

    def test_get_read_group_order_aggregator_fallback_and_no_duplicate(self):
        """``_get_read_group_order`` must fall back to a field's aggregator and
        not emit duplicate ORDER BY terms.

        Regression: dropping upstream's nested ``for/else`` (a) silently
        discarded ordering by an aggregatable field absent from groupby and
        aggregates, and (b) appended a second, conflicting term for a field
        present in both a groupby and an aggregate.
        """
        Model = self.env["res.partner"]
        agg_field = next(
            (
                n
                for n, f in Model._fields.items()
                if getattr(f, "aggregator", None) and f.store
            ),
            None,
        )
        self.assertIsNotNone(
            agg_field, "expected a stored aggregatable field on res.partner"
        )
        aggregator = Model._fields[agg_field].aggregator

        # (a) aggregator fallback: not in groupby/aggregates -> sort by aggregate.
        order = Model._get_read_group_order(
            {agg_field: "desc"}, groupby=["country_id"], aggregates=[]
        )
        self.assertIn(
            f"{agg_field}:{aggregator} desc",
            order,
            "ordering by an aggregatable field must fall back to its aggregator, not be dropped",
        )

        # (b) no duplicate: a field matching both a groupby and an aggregate
        # must yield only the groupby term.
        order2 = Model._get_read_group_order(
            {"create_date": "desc"},
            groupby=["create_date:month"],
            aggregates=["create_date:max"],
        )
        self.assertEqual(order2, "create_date:month desc")
