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

    def test_client_res_model_cannot_override_the_filter_model(self):
        """A saved filter's model is not negotiable by the caller.

        ``res_model`` is client-supplied on the public route. Letting it win ran
        the designer's domain / sort / context against a model of the visitor's
        choosing — a filter over ``res.partner`` would happily return
        ``res.lang`` rows.
        """
        result = self.snippet_filter._prepare_values(
            limit=16, search_domain=[], res_model="res.lang"
        )
        self.assertTrue(result, "The filter's own model must still be queried.")
        names = {row["name"] for row in result}
        self.assertIn("PUBLIC_MEMBER", names)
        self.assertNotIn(
            "English (US)", names, "res.lang records must never leak through."
        )

    def test_unknown_res_model_does_not_raise(self):
        """An unknown model name used to reach ``self.env[...]`` as a KeyError,
        i.e. an unauthenticated traceback on a public route."""
        no_filter = self.env["website.snippet.filter"]
        self.assertEqual(
            no_filter._prepare_values(
                limit=1, search_domain=[], res_model="not.a.model", res_id=1
            ),
            [],
        )

    def test_filterless_single_record_does_not_crash_on_blank_field_names(self):
        """The filter-less single-record path has no ``field_names``.

        It falls back to the field's ``""`` default, and a bare ``split(",")``
        then yields one empty name that reaches ``record[""]`` — an
        unauthenticated ``KeyError`` on a public route.
        """
        no_filter = self.env["website.snippet.filter"]
        result = no_filter._prepare_values(
            limit=1,
            search_domain=[],
            res_model="res.partner",
            res_id=self.published.id,
        )
        self.assertEqual(len(result), 1)
        self.assertNotIn("", result[0], "A blank field name must be skipped.")

    def test_blank_and_padded_field_names_are_skipped_or_trimmed(self):
        Partner = self.env["res.partner"]
        Filter = self.env["website.snippet.filter"]
        self.snippet_filter.invalidate_recordset()
        meta = self.snippet_filter._get_filter_meta_data(Partner)
        self.assertEqual(list(meta), ["name", "email", "phone"])
        self.assertEqual(list(Filter._get_filter_meta_data(Partner)), [])

    def test_render_tolerates_a_malformed_public_payload(self):
        """Every ``_render`` argument comes straight from an unauthenticated
        JSON-RPC caller, so a missing/garbage one must yield [] rather than a
        ``TypeError``/``ValueError`` 500."""
        self.assertEqual(self.snippet_filter._render(), [])
        self.assertEqual(self.snippet_filter._render(template_key=None, limit=4), [])
        self.assertEqual(
            self.snippet_filter._render(template_key="website.not_a_filter_template"),
            [],
        )

    def test_limit_and_res_id_are_coerced(self):
        """JSON-RPC delivers whatever the caller typed; non-integers must not
        blow up inside ``min()`` or a domain leaf."""
        Filter = self.env["website.snippet.filter"]
        self.assertIsNone(Filter._coerce_positive_int("abc"))
        self.assertIsNone(Filter._coerce_positive_int(None))
        self.assertIsNone(Filter._coerce_positive_int(True))
        self.assertIsNone(Filter._coerce_positive_int([1]))
        self.assertIsNone(Filter._coerce_positive_int(0))
        self.assertIsNone(Filter._coerce_positive_int(-3))
        self.assertEqual(Filter._coerce_positive_int("7"), 7)
        self.assertEqual(Filter._coerce_positive_int(7.9), 7)
        # A string limit used to raise TypeError in min(limit, max_limit).
        self.assertTrue(
            self.snippet_filter._prepare_values(limit="2", search_domain=[])
        )
