from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebHierarchyView(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env["ir.ui.view"]

    def _validate(self, xml):
        self.View._check_view_tag_hierarchy(
            etree.fromstring(xml), None, {"validate": True}
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
        self._validate('<hierarchy><field name="parent_id"/><templates/></hierarchy>')

    def test_validate_rejects_unknown_child_tag(self):
        """Only field and templates children are allowed."""
        with self.assertRaises(ValueError):
            self._validate("<hierarchy><group/></hierarchy>")

    def test_validate_rejects_multiple_templates(self):
        """At most one templates tag is allowed in a hierarchy view."""
        with self.assertRaises(ValueError):
            self._validate("<hierarchy><templates/><templates/></hierarchy>")

    def test_validate_rejects_invalid_attribute(self):
        """Attributes outside the hierarchy whitelist are rejected."""
        with self.assertRaises(ValueError):
            self._validate('<hierarchy bogus="1"><field name="parent_id"/></hierarchy>')

    def test_validate_skipped_when_not_validating(self):
        """Validation is a no-op when node_info disables it."""
        # an otherwise-invalid node passes because validation is off
        self.View._check_view_tag_hierarchy(
            etree.fromstring("<hierarchy><group/></hierarchy>"),
            None,
            {"validate": False},
        )

    # ── hierarchy_read ──────────────────────────────────────────────────

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
