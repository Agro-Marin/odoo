from odoo.tests import TransactionCase, tagged


@tagged("web_unit", "web_read_group")
class TestWebReadGroup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create(
            [
                {"name": "WRG Test Company 1", "is_company": True},
                {"name": "WRG Test Company 2", "is_company": True},
                {"name": "WRG Test Person 1", "is_company": False},
            ]
        )
        cls.domain = [("id", "in", cls.partners.ids)]

    def test_open_groups_zero_max_disables_auto_open(self):
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
        with self.assertRaises(ValueError):
            self.env["res.partner"]._add_groupby_values(
                groupby_read_specification={"create_date:month": {}},
                groupby=["create_date:month"],
                current_groups=[],
            )

    def test_read_progress_bar_datetime_keys_match_client_non_utc(self):
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
        total = sum(sum(states.values()) for states in pb.values())
        self.assertEqual(total, len(self.partners))

    def test_web_read_group_length_counts_all_groups_when_page_full(self):
        Partner = self.env["res.partner"]
        partners = Partner.create([{"name": f"WRG Count {i}"} for i in range(5)])
        domain = [("id", "in", partners.ids)]
        result = Partner.web_read_group(
            domain=domain, groupby=["name"], aggregates=["__count"], limit=2
        )
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["length"], 5)

    def test_read_group_count_matches_len_read_group(self):
        Partner = self.env["res.partner"]
        for groupby in (["is_company"], ["name"], ["country_id"], ["parent_id"]):
            expected = len(Partner._read_group(self.domain, groupby=groupby))
            self.assertEqual(
                Partner._read_group_count(self.domain, groupby),
                expected,
                f"count mismatch for groupby={groupby}",
            )

    def test_read_group_count_edge_cases(self):
        Partner = self.env["res.partner"]
        self.assertEqual(
            Partner._read_group_count([("id", "in", [])], ["is_company"]), 0
        )
        self.assertEqual(Partner._read_group_count(self.domain, []), 1)

    def test_get_read_group_order_aggregator_fallback_and_no_duplicate(self):
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

        order = Model._get_read_group_order(
            {agg_field: "desc"}, groupby=["country_id"], aggregates=[]
        )
        self.assertIn(
            f"{agg_field}:{aggregator} desc",
            order,
            "ordering by an aggregatable field must fall back to its aggregator, not be dropped",
        )

        order2 = Model._get_read_group_order(
            {"create_date": "desc"},
            groupby=["create_date:month"],
            aggregates=["create_date:max"],
        )
        self.assertEqual(order2, "create_date:month desc")


@tagged("web_unit", "web_read_group")
class TestWebReadGroupContracts(TransactionCase):
    def test_group_pagination_order_no_dup_no_loss(self):
        Partner = self.env["res.partner"]
        partners = Partner.create(
            [
                {"name": "WRG Page Tie", "function": "fA" if i % 2 else "fB"}
                for i in range(120)
            ]
        )
        domain = [("id", "in", partners.ids)]
        result = Partner.web_read_group(
            domain=domain,
            groupby=["is_company"],
            aggregates=["__count"],
            order="function ASC",
            auto_unfold=True,
            unfold_read_specification={"id": {}},
            unfold_read_default_limit=80,
        )
        [group] = result["groups"]
        page1 = [rec["id"] for rec in group["__records"]]
        self.assertEqual(len(page1), 80)

        page2 = [
            rec["id"]
            for rec in Partner.web_search_read(
                domain=domain,
                specification={"id": {}},
                offset=80,
                limit=80,
                order="function ASC, id",
            )["records"]
        ]
        self.assertEqual(len(page2), 40)
        self.assertFalse(set(page1) & set(page2), "no record may appear on two pages")
        self.assertEqual(
            set(page1) | set(page2),
            set(partners.ids),
            "no record may be lost between pages",
        )
        expected = [p.id for p in sorted(partners, key=lambda p: (p.function, p.id))]
        self.assertEqual(page1, expected[:80])
        self.assertEqual(page2, expected[80:])

    def _make_function_groups(self, count):
        partners = self.env["res.partner"].create(
            [
                {"name": f"WRG Fold {i}", "function": f"wrgfn{i:02d}"}
                for i in range(count)
            ]
        )
        return partners, [("id", "in", partners.ids)]

    def test_opening_info_restores_more_groups_than_auto_cap(self):
        _partners, domain = self._make_function_groups(12)
        opening_info = [{"value": f"wrgfn{i:02d}", "folded": False} for i in range(12)]
        result = self.env["res.partner"].web_read_group(
            domain=domain,
            groupby=["function"],
            aggregates=["__count"],
            opening_info=opening_info,
            unfold_read_specification={"id": {}},
        )
        self.assertEqual(len(result["groups"]), 12)
        for group in result["groups"]:
            self.assertIn(
                "__records",
                group,
                f"explicitly-opened group {group['function']!r} must be restored open",
            )
            self.assertEqual(len(group["__records"]), 1)

    def test_auto_unfold_cap_still_ten(self):
        _partners, domain = self._make_function_groups(12)
        result = self.env["res.partner"].web_read_group(
            domain=domain,
            groupby=["function"],
            aggregates=["__count"],
            auto_unfold=True,
            unfold_read_specification={"id": {}},
        )
        opened = [g for g in result["groups"] if "__records" in g]
        self.assertEqual(len(opened), 10, "auto-unfold must stop at 10 groups")

    def test_progressbar_domain_filters_aggregates_keeps_count(self):
        Partner = self.env["res.partner"]
        Partner.create(
            [
                {
                    "name": f"WRG PB {i}",
                    "function": "wrgpb",
                    "is_company": i < 5,
                    "color": 7,
                }
                for i in range(10)
            ]
        )
        domain = [("function", "=", "wrgpb")]
        result = Partner.web_read_group(
            domain=domain,
            groupby=["function"],
            aggregates=["color:sum"],
            opening_info=[
                {
                    "value": "wrgpb",
                    "folded": False,
                    "offset": 0,
                    "limit": 80,
                    "progressbar_domain": [("is_company", "=", True)],
                }
            ],
            unfold_read_specification={"id": {}},
        )
        [group] = result["groups"]
        self.assertEqual(group["__count"], 10, "__count must stay unfiltered")
        self.assertEqual(
            group["color:sum"], 35, "aggregates must be progressbar-filtered"
        )
        self.assertEqual(len(group["__records"]), 5)

        result = Partner.web_read_group(
            domain=domain,
            groupby=["function"],
            aggregates=["color:sum"],
            opening_info=[{"value": "wrgpb", "folded": False}],
            unfold_read_specification={"id": {}},
        )
        [group] = result["groups"]
        self.assertEqual(group["__count"], 10)
        self.assertEqual(group["color:sum"], 70)
        self.assertEqual(len(group["__records"]), 10)

    def test_fill_temporal_ignored_with_limit_or_offset(self):
        Partner = self.env["res.partner"]
        partner = Partner.create({"name": "WRG FT"})
        domain = [("id", "=", partner.id)]
        model = Partner.with_context(fill_temporal=True)

        result = model.web_read_group(
            domain, ["create_date:month"], ["__count"], limit=80
        )
        self.assertEqual(result["groups"][0]["__count"], 1)

        result = model.web_read_group(
            domain, ["create_date:month"], ["__count"], limit=80, offset=1
        )
        self.assertEqual(result["groups"], [])

        with self.assertRaises(ValueError):
            model.formatted_read_group(
                domain, ["create_date:month"], ["__count"], limit=80
            )


@tagged("web_unit", "web_read_group")
class TestSearchOpenedGroupsBatching(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.parents = Partner.create(
            [{"name": f"SOG P{i:03d}", "is_company": True} for i in range(60)]
        )
        Partner.create(
            [
                {
                    "name": f"SOG C{i:03d}-{j:02d}",
                    "parent_id": parent.id,
                    "ref": f"TIE{j % 3}",
                }
                for i, parent in enumerate(cls.parents)
                for j in range(10)
            ]
        )
        cls.domain = [("parent_id", "in", cls.parents.ids)]

    def _records_per_group(self, n_groups, order, limit, offset):
        Partner = self.env["res.partner"]
        groups = Partner.formatted_read_group(self.domain, ["parent_id"], ["__count"])
        opening = [
            {
                "value": group["parent_id"][0],
                "folded": False,
                "offset": offset,
                "limit": limit,
            }
            for group in groups[:n_groups]
        ]
        self.env.invalidate_all()
        result = Partner.with_context(max_number_opened_groups=100000).web_read_group(
            self.domain,
            ["parent_id"],
            ["__count"],
            order=order,
            opening_info=opening,
            unfold_read_specification={"display_name": {}},
        )
        return [
            [record["id"] for record in group.get("__records", [])]
            for group in result["groups"]
        ]

    def test_batched_matches_per_group_search(self):
        Base = type(self.env["res.partner"])
        batched = Base._get_records_opened_groups

        def per_group(model, records_opening_info, domain, order_searches):
            return [
                (
                    model.search(
                        domain & sub["domain"],
                        order=order_searches,
                        limit=sub["limit"],
                        offset=sub["offset"],
                    )
                    if sub["group"]["__count"]
                    else model.browse()
                )
                for sub in records_opening_info
            ]

        scenarios = [
            (n, order, limit, offset)
            for n in (1, 2, 7, 55, 60)
            for order in (None, "name desc", "ref asc", "ref desc, name asc")
            for limit in (3, 20)
            for offset in (0, 2)
        ]
        try:
            for n, order, limit, offset in scenarios:
                with self.subTest(n=n, order=order, limit=limit, offset=offset):
                    Base._get_records_opened_groups = per_group
                    expected = self._records_per_group(n, order, limit, offset)
                    Base._get_records_opened_groups = batched
                    actual = self._records_per_group(n, order, limit, offset)
                    self.assertEqual(actual, expected)
        finally:
            Base._get_records_opened_groups = batched

    def test_batching_collapses_round_trips(self):
        n_groups = 60
        self.env.invalidate_all()
        self.env.cr.flush()
        before = self.env.cr.sql_log_count
        self._records_per_group(n_groups, None, 5, 0)
        queries = self.env.cr.sql_log_count - before
        self.assertLess(
            queries,
            n_groups // 2,
            f"expected batched fetch, got {queries} queries for {n_groups} groups",
        )
