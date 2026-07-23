# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebHierarchyView(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.View = cls.env["ir.ui.view"]

    def _validate(self, xml):
        self.View._validate_tag_hierarchy(
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

    # ── _validate_tag_hierarchy ──────────────────────────────────────

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
        self.View._validate_tag_hierarchy(
            etree.fromstring("<hierarchy><group/></hierarchy>"),
            None,
            {"validate": False},
        )
