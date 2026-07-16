# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSnippetFilterSecurity(TransactionCase):
    """Regression tests for the dynamic-snippet-filter ``_prepare_values``
    single-record path, which is reachable unauthenticated through
    ``/website/snippet/filters`` (``get_dynamic_filter``)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")
        # A published "Our Team" style filter over res.partner, exactly what a
        # site builder configures for a dynamic snippet.
        cls.ir_filter = cls.env["ir.filters"].create(
            {
                "name": "Team",
                "model_id": "res.partner",
                "domain": "[('is_published', '=', True)]",
                "context": "{}",
                "sort": '["id"]',
            }
        )
        cls.snippet_filter = cls.env["website.snippet.filter"].create(
            {
                "name": "Our Team",
                "filter_id": cls.ir_filter.id,
                "limit": 16,
                "field_names": "name,email,phone",
                "website_published": True,
            }
        )
        cls.published = cls.env["res.partner"].create(
            {
                "name": "PUBLIC_MEMBER",
                "email": "team@shown.example",
                "is_published": True,
            }
        )
        cls.secret = cls.env["res.partner"].create(
            {
                "name": "SECRET_UNPUBLISHED",
                "email": "secret@hidden.example",
                "phone": "555-SECRET",
                "is_published": False,
            }
        )

    def _public_filter(self):
        """The recordset the public controller resolves before rendering."""
        public = self.env.ref("base.public_user")
        penv = self.env(user=public.id, su=False)
        return (
            penv["website.snippet.filter"]
            .sudo()
            .search(
                Domain("id", "=", self.snippet_filter.id)
                & penv["website"].get_current_website().website_domain()
            )
        )

    def test_single_record_cannot_read_unpublished(self):
        """The single-record path (limit=1 + res_model + res_id) must not let a
        caller read an *unpublished* record by id — that would bypass the
        filter's publication scoping (IDOR)."""
        result = self._public_filter()._prepare_values(
            limit=1,
            search_domain=[],
            res_model="res.partner",
            res_id=self.secret.id,
        )
        self.assertEqual(result, [], "An unpublished record must not be exposed by id.")
        self.assertNotIn("SECRET_UNPUBLISHED", str(result))

    def test_single_record_still_returns_published(self):
        """Legitimate single-record use (a published record) keeps working."""
        result = self.snippet_filter._prepare_values(
            limit=1,
            search_domain=[],
            res_model="res.partner",
            res_id=self.published.id,
        )
        self.assertTrue(result)
        self.assertEqual(result[0]["name"], "PUBLIC_MEMBER")

    def test_public_search_domain_field_is_validated(self):
        """A client-supplied search domain may only reference real fields."""
        with self.assertRaises(ValueError):
            self.snippet_filter._prepare_values(
                limit=16,
                search_domain=[("not_a_field", "=", 1)],
                res_model="res.partner",
            )

    def test_public_search_domain_rejects_relational_traversal(self):
        """A client-supplied domain may only reference *direct* fields. Dotted
        paths (e.g. ``create_uid.login``) passed the old ``split('.')[0]`` check
        and let a public visitor filter on related — possibly unpublished —
        records, turning the published result set into a boolean oracle."""
        for dotted in ("create_uid.login", "parent_id.vat", "company_id.name"):
            with self.assertRaises(ValueError, msg=f"{dotted} must be rejected"):
                self.snippet_filter._prepare_values(
                    limit=16,
                    search_domain=[(dotted, "ilike", "x")],
                    res_model="res.partner",
                )
        # A direct field is still accepted (no false positive on the fix).
        self.snippet_filter._prepare_values(
            limit=16,
            search_domain=[("name", "ilike", "PUBLIC")],
            res_model="res.partner",
        )
