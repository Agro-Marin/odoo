from types import SimpleNamespace

from lxml import etree

from odoo.tests import TransactionCase, tagged

CARD = "<templates><t t-name='hierarchy-box'><field name='name'/></t></templates>"


@tagged("post_install", "-at_install")
class TestWebHierarchyView(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env["ir.ui.view"]

    def _validate(self, xml, model="res.partner"):
        name_manager = SimpleNamespace(model=self.env[model]) if model else None
        self.View._check_view_tag_hierarchy(
            etree.fromstring(xml), name_manager, {"validate": True}
        )

    # ── view type registration ───────────────────────────────────────

    def test_hierarchy_is_qweb_based(self):
        """The hierarchy view type is treated as a qweb-based view."""
        self.assertTrue(self.View._is_qweb_based_view("hierarchy"))

    def test_form_is_not_qweb_based(self):
        """A non-hierarchy, non-qweb view type stays non-qweb-based."""
        self.assertFalse(self.View._is_qweb_based_view("form"))

    def test_view_info_declares_hierarchy(self):
        """The hierarchy view exposes its info (icon) to the view registry."""
        info = self.View._get_view_info()
        self.assertIn("hierarchy", info)
        self.assertTrue(info["hierarchy"]["icon"])

    # ── _check_view_tag_hierarchy ──────────────────────────────────────

    def test_validate_accepts_fields_and_single_template(self):
        """A hierarchy of fields and one templates tag validates."""
        # no exception expected
        self._validate(f'<hierarchy><field name="parent_id"/>{CARD}</hierarchy>')

    def test_validate_rejects_unknown_child_tag(self):
        """Only field and templates children are allowed."""
        with self.assertRaises(ValueError):
            self._validate(f"<hierarchy><group/>{CARD}</hierarchy>")

    def test_validate_rejects_multiple_templates(self):
        """At most one templates tag is allowed in a hierarchy view."""
        with self.assertRaises(ValueError):
            self._validate(f"<hierarchy>{CARD}{CARD}</hierarchy>")

    def test_validate_rejects_invalid_attribute(self):
        """Attributes outside the hierarchy whitelist are rejected."""
        with self.assertRaises(ValueError):
            self._validate(f'<hierarchy bogus="1">{CARD}</hierarchy>')

    def test_validate_rejects_missing_card_template(self):
        """The client cannot render a card without a hierarchy-box template."""
        with self.assertRaises(ValueError):
            self._validate('<hierarchy><field name="parent_id"/></hierarchy>')

    def test_validate_rejects_unknown_parent_field(self):
        """A parent_field naming nothing is refused with the view, not in the browser."""
        with self.assertRaises(ValueError):
            self._validate(f'<hierarchy parent_field="nope">{CARD}</hierarchy>')

    def test_validate_rejects_parent_field_of_wrong_type(self):
        """parent_field must be a many2one."""
        with self.assertRaises(ValueError):
            self._validate(f'<hierarchy parent_field="name">{CARD}</hierarchy>')

    def test_validate_rejects_parent_field_on_another_model(self):
        """parent_field must point back at the model of the view."""
        with self.assertRaises(ValueError):
            self._validate(f'<hierarchy parent_field="company_id">{CARD}</hierarchy>')

    def test_validate_rejects_child_field_of_wrong_type(self):
        """child_field must be a one2many, not the many2one holding the parent."""
        with self.assertRaises(ValueError):
            self._validate(f'<hierarchy child_field="parent_id">{CARD}</hierarchy>')

    def test_validate_accepts_matching_relation_fields(self):
        """The self-referencing pair of res.partner validates."""
        # no exception expected
        self._validate(
            f'<hierarchy parent_field="parent_id" child_field="child_ids">{CARD}</hierarchy>'
        )

    def test_validate_skipped_when_not_validating(self):
        """Validation is a no-op when node_info disables it."""
        # an otherwise-invalid node passes because validation is off
        self.View._check_view_tag_hierarchy(
            etree.fromstring("<hierarchy><group/></hierarchy>"),
            None,
            {"validate": False},
        )

    # ── hierarchy_read ──────────────────────────────────────────────────

    def test_hierarchy_read_is_readonly(self):
        """hierarchy_read only reads, and says so, like web_read does."""
        Partner = type(self.env["res.partner"])
        self.assertTrue(getattr(Partner.hierarchy_read, "_readonly", False))

    def test_hierarchy_read_does_not_mutate_the_given_specification(self):
        """The parent field is added to a copy, not to the caller's dict."""
        partner = self.env["res.partner"].create({"name": "Standalone"})
        specification = {"name": {}}
        self.env["res.partner"].hierarchy_read(
            [("id", "=", partner.id)], specification, "parent_id"
        )
        self.assertEqual(specification, {"name": {}})

    def test_hierarchy_read_returns_the_parent_display_name(self):
        """The parent field is read even when the view did not ask for it."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        [record] = [
            r
            for r in Partner.hierarchy_read(
                [("id", "=", child.id)], {"name": {}}, "parent_id"
            )
            if r["id"] == child.id
        ]
        self.assertEqual(record["parent_id"]["display_name"], "Parent")

    def test_hierarchy_read_empty_domain(self):
        """A domain matching nothing returns an empty list."""
        result = self.env["res.partner"].hierarchy_read(
            [("id", "=", 0)], {"name": {}}, "parent_id"
        )
        self.assertEqual(result, [])

    def test_hierarchy_read_single_record_no_parent_no_children(self):
        """A lone record with no parent and no children returns just itself."""
        partner = self.env["res.partner"].create({"name": "Standalone"})
        result = self.env["res.partner"].hierarchy_read(
            [("id", "=", partner.id)], {"name": {}}, "parent_id"
        )
        self.assertEqual([r["id"] for r in result], [partner.id])
        self.assertNotIn("__child_ids__", result[0])

    def test_hierarchy_read_single_record_expands_parent_and_siblings(self):
        """Focusing on one child also returns its parent and siblings."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child1 = Partner.create({"name": "Child 1", "parent_id": parent.id})
        child2 = Partner.create({"name": "Child 2", "parent_id": parent.id})
        result = Partner.hierarchy_read(
            [("id", "=", child1.id)], {"name": {}}, "parent_id"
        )
        self.assertEqual({r["id"] for r in result}, {parent.id, child1.id, child2.id})

    def test_hierarchy_read_single_record_expands_own_children(self):
        """Focusing on a parentless record returns the children it has."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        result = Partner.hierarchy_read(
            [("id", "=", parent.id)], {"name": {}}, "parent_id"
        )
        self.assertEqual({r["id"] for r in result}, {parent.id, child.id})

    def test_hierarchy_read_single_record_skips_child_ids_of_shown_parents(self):
        """A record whose children are already in the payload advertises none."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        grandchild = Partner.create({"name": "Grandchild", "parent_id": child.id})
        by_id = {
            r["id"]: r
            for r in Partner.hierarchy_read(
                [("id", "=", child.id)], {"name": {}}, "parent_id"
            )
        }
        # child's children are displayed, so it needs no child ids; the
        # grandchild has none at all.
        self.assertNotIn("__child_ids__", by_id[child.id])
        self.assertNotIn("__child_ids__", by_id[grandchild.id])

    def test_hierarchy_read_multi_match_computes_child_ids(self):
        """Multiple matches compute __child_ids__ per matched record via read_group."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child1 = Partner.create({"name": "Child 1", "parent_id": parent.id})
        child2 = Partner.create({"name": "Child 2", "parent_id": parent.id})
        other = Partner.create({"name": "Other"})
        result = Partner.hierarchy_read(
            [("id", "in", [parent.id, other.id])], {"name": {}}, "parent_id"
        )
        by_id = {r["id"]: r for r in result}
        self.assertEqual(set(by_id[parent.id]["__child_ids__"]), {child1.id, child2.id})
        self.assertNotIn("__child_ids__", by_id[other.id])

    def test_hierarchy_read_multi_match_keeps_child_ids_of_shown_parents(self):
        """Every match gets its child ids when the domain matched several records."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        grandchild = Partner.create({"name": "Grandchild", "parent_id": child.id})
        by_id = {
            r["id"]: r
            for r in Partner.hierarchy_read(
                [("id", "in", [parent.id, child.id])], {"name": {}}, "parent_id"
            )
        }
        self.assertEqual(by_id[parent.id]["__child_ids__"], [child.id])
        self.assertEqual(by_id[child.id]["__child_ids__"], [grandchild.id])

    def test_hierarchy_read_explicit_child_field_skips_read_group(self):
        """An explicit child_field means the server never adds __child_ids__."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        Partner.create({"name": "Child", "parent_id": parent.id})
        result = Partner.hierarchy_read(
            [("id", "=", parent.id)],
            {"name": {}},
            "parent_id",
            child_field="child_ids",
        )
        self.assertNotIn("__child_ids__", result[0])

    def test_hierarchy_read_order_on_non_groupby_field(self):
        """A default_order naming a plain field must not crash (see F001)."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        other = Partner.create({"name": "Other"})
        result = Partner.hierarchy_read(
            [("id", "in", [parent.id, other.id])],
            {"name": {}},
            "parent_id",
            order="name",
        )
        self.assertEqual(len(result), 2)

    def test_hierarchy_read_orders_the_records(self):
        """The requested order is the order of the answer."""
        Partner = self.env["res.partner"]
        beta = Partner.create({"name": "ZZ Beta"})
        alpha = Partner.create({"name": "ZZ Alpha"})
        result = Partner.hierarchy_read(
            [("id", "in", [beta.id, alpha.id])],
            {"name": {}},
            "parent_id",
            order="name asc",
        )
        self.assertEqual([r["id"] for r in result], [alpha.id, beta.id])

    # ── only_roots ──────────────────────────────────────────────────────

    def test_only_roots_restricts_to_parentless_records(self):
        """only_roots keeps the records that have no parent."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        result = Partner.hierarchy_read(
            [("id", "in", [parent.id, child.id])],
            {"name": {}},
            "parent_id",
            only_roots=True,
        )
        self.assertEqual([r["id"] for r in result], [parent.id, child.id])
        self.assertEqual(result[0]["parent_id"], False)

    def test_only_roots_falls_back_within_one_request(self):
        """When no root matches, the domain alone answers -- here, not in a second call."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        with_roots = Partner.hierarchy_read(
            [("id", "=", child.id)], {"name": {}}, "parent_id", only_roots=True
        )
        without = Partner.hierarchy_read(
            [("id", "=", child.id)], {"name": {}}, "parent_id", only_roots=False
        )
        self.assertEqual([r["id"] for r in with_roots], [r["id"] for r in without])
        self.assertIn(parent.id, [r["id"] for r in with_roots])

    def test_only_roots_returns_nothing_when_the_domain_matches_nothing(self):
        """The fallback answers the domain, not the whole table."""
        result = self.env["res.partner"].hierarchy_read(
            [("id", "=", 0)], {"name": {}}, "parent_id", only_roots=True
        )
        self.assertEqual(result, [])

    # ── archived records ────────────────────────────────────────────────

    def test_archived_parent_is_left_out_like_any_archived_record(self):
        """An archived parent obeys active_test, as an archived sibling already did."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        sibling = Partner.create({"name": "Sibling", "parent_id": parent.id})

        active = Partner.hierarchy_read(
            [("id", "=", child.id)], {"name": {}}, "parent_id"
        )
        self.assertEqual({r["id"] for r in active}, {parent.id, child.id, sibling.id})

        parent.active = False
        archived_parent = Partner.hierarchy_read(
            [("id", "=", child.id)], {"name": {}}, "parent_id"
        )
        self.assertNotIn(
            parent.id,
            [r["id"] for r in archived_parent],
            "an archived parent is no more visible here than in any other view",
        )
        self.assertEqual({r["id"] for r in archived_parent}, {child.id, sibling.id})

    def test_archived_parent_comes_back_with_active_test_off(self):
        """The whole payload obeys one switch, so the caller can still ask for it."""
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent"})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        parent.active = False
        result = Partner.with_context(active_test=False).hierarchy_read(
            [("id", "=", child.id)], {"name": {}}, "parent_id"
        )
        self.assertIn(parent.id, [r["id"] for r in result])
