from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSnippetFilterSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")
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
        result = self._public_filter()._prepare_values(
            limit=1,
            search_domain=[],
            res_model="res.partner",
            res_id=self.secret.id,
        )
        self.assertEqual(result, [], "An unpublished record must not be exposed by id.")
        self.assertNotIn("SECRET_UNPUBLISHED", str(result))

    def test_single_record_still_returns_published(self):
        result = self.snippet_filter._prepare_values(
            limit=1,
            search_domain=[],
            res_model="res.partner",
            res_id=self.published.id,
        )
        self.assertTrue(result)
        self.assertEqual(result[0]["name"], "PUBLIC_MEMBER")

    def test_public_search_domain_field_is_validated(self):
        with self.assertRaises(ValueError):
            self.snippet_filter._prepare_values(
                limit=16,
                search_domain=[("not_a_field", "=", 1)],
                res_model="res.partner",
            )

    def test_public_search_domain_rejects_relational_traversal(self):
        for dotted in ("create_uid.login", "parent_id.vat", "company_id.name"):
            with self.assertRaises(ValueError, msg=f"{dotted} must be rejected"):
                self.snippet_filter._prepare_values(
                    limit=16,
                    search_domain=[(dotted, "ilike", "x")],
                    res_model="res.partner",
                )
        self.snippet_filter._prepare_values(
            limit=16,
            search_domain=[("name", "ilike", "PUBLIC")],
            res_model="res.partner",
        )

    def test_client_res_model_cannot_override_the_filter_model(self):
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
        no_filter = self.env["website.snippet.filter"]
        self.assertEqual(
            no_filter._prepare_values(
                limit=1, search_domain=[], res_model="not.a.model", res_id=1
            ),
            [],
        )

    def test_filterless_single_record_does_not_crash_on_blank_field_names(self):
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
        self.assertEqual(self.snippet_filter._render(), [])
        self.assertEqual(self.snippet_filter._render(template_key=None, limit=4), [])
        self.assertEqual(
            self.snippet_filter._render(template_key="website.not_a_filter_template"),
            [],
        )

    def test_limit_and_res_id_are_coerced(self):
        Filter = self.env["website.snippet.filter"]
        self.assertIsNone(Filter._coerce_positive_int("abc"))
        self.assertIsNone(Filter._coerce_positive_int(None))
        self.assertIsNone(Filter._coerce_positive_int(True))
        self.assertIsNone(Filter._coerce_positive_int([1]))
        self.assertIsNone(Filter._coerce_positive_int(0))
        self.assertIsNone(Filter._coerce_positive_int(-3))
        self.assertEqual(Filter._coerce_positive_int("7"), 7)
        self.assertEqual(Filter._coerce_positive_int(7.9), 7)
        self.assertTrue(
            self.snippet_filter._prepare_values(limit="2", search_domain=[])
        )
