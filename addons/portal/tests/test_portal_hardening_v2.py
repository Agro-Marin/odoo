"""Second pass over portal's request-handling edges.

Each case here is a value the framework hands a controller in a shape the
controller did not consider: a report type it accepts but does not label, a
form field sent as a file, a JSON flag sent as a container, a URL field asked
for on a record the customer never opened.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.portal.controllers.portal import (
    _as_password_field,
    _pager_url,
    get_records_pager,
)


class _ReportableModel:
    """Stands in for a record that can name its report file.

    ``_get_report_base_filename`` is contributed by the report-bearing models,
    not by ``res.partner``; a stub keeps this test independent of which addons
    happen to be installed alongside portal.
    """

    def _get_report_base_filename(self):
        return "Invoice INV/2024/0001"


@tagged("-at_install", "post_install")
class TestReportContentType(TransactionCase):
    """``_show_report`` accepts html, pdf and text; the header must say which."""

    def test_content_type_per_report_type(self):
        from odoo.addons.portal.controllers.portal import CustomerPortal

        controller = CustomerPortal()
        expected = {
            "pdf": "application/pdf",
            "html": "text/html",
            # Was "text/html", so a browser parsed a plain-text report as
            # markup: any "<" in the payload opened a tag.
            "text": "text/plain",
        }
        for report_type, content_type in expected.items():
            with self.subTest(report_type=report_type):
                headers = controller._get_http_headers(
                    _ReportableModel(), report_type, "body", download=False
                )

                self.assertEqual(headers["Content-Type"], content_type)

    def test_unknown_report_type_still_gets_a_content_type(self):
        """``_show_report`` rejects other types, but the mapping must not KeyError."""
        from odoo.addons.portal.controllers.portal import CustomerPortal

        headers = CustomerPortal()._get_http_headers(
            _ReportableModel(), "something-else", "body", download=False
        )

        self.assertEqual(headers["Content-Type"], "text/html")

    def test_content_length_is_the_byte_count(self):
        from odoo.addons.portal.controllers.portal import CustomerPortal

        # Multi-byte content: the char count and the byte count differ.
        headers = CustomerPortal()._get_http_headers(
            _ReportableModel(), "text", "é" * 5, False
        )

        self.assertEqual(headers["Content-Length"], 10)

    def test_pdf_still_gets_a_sanitised_filename(self):
        from odoo.addons.portal.controllers.portal import CustomerPortal

        headers = CustomerPortal()._get_http_headers(
            _ReportableModel(), "pdf", b"%PDF-", download=True
        )

        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("Invoice_INV_2024_0001.pdf", headers["Content-Disposition"])


@tagged("-at_install", "post_install")
class TestPasswordFieldCoercion(TransactionCase):
    """A password field that is not text is not a password."""

    def test_text_is_stripped(self):
        self.assertEqual(_as_password_field("  hunter2  "), "hunter2")

    def test_non_text_reads_as_absent(self):
        class FakeUpload:
            """Stands in for werkzeug's FileStorage: no ``strip``."""

        for raw in (None, FakeUpload(), 42, [], {}):
            with self.subTest(raw=type(raw).__name__):
                # The point is that this does not raise AttributeError.
                self.assertEqual(_as_password_field(raw), "")


@tagged("-at_install", "post_install")
class TestPagerTokenMinting(TransactionCase):
    """Rendering a document page must not persist tokens on other records."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.records = cls.env["res.partner"].create(
            [{"name": "Pager A"}, {"name": "Pager B"}]
        )

    def test_no_pager_when_the_record_is_not_in_the_history(self):
        """The navigation sequence has to contain the record being viewed.

        Deliberately not asserting on "a model with no URL field" instead: which
        fields ``res.partner`` carries depends on what else is installed
        (``website`` contributes ``website_url``), so that premise holds only in
        some module combinations.
        """
        result = get_records_pager([-1, -2], self.records[0])

        self.assertEqual(result, {})

    def test_without_token_no_write_happens(self):
        """``with_token=False`` must not call ``_portal_ensure_token``."""
        calls = []

        class FakeRecord:
            _name = "fake"

            def __getitem__(self, key):
                return "/my/fake/1"

            def __bool__(self):
                return True

            def _portal_ensure_token(self):
                calls.append(1)
                return "tok"

        record = FakeRecord()
        self.assertEqual(_pager_url(record, "access_url", False), "/my/fake/1")
        self.assertEqual(calls, [], "a token was minted for a non-token visitor")

        # ...and the token-authenticated caller still gets one.
        self.assertEqual(
            _pager_url(record, "access_url", True), "/my/fake/1?access_token=tok"
        )
        self.assertEqual(calls, [1])


@tagged("-at_install", "post_install")
class TestBillingAddressDomain(TransactionCase):
    """The billing domain is now a model hook, like its delivery counterpart."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.company = Partner.create({"name": "Domain Co", "is_company": True})
        cls.invoice = Partner.create(
            {"name": "Inv", "parent_id": cls.company.id, "type": "invoice"}
        )
        cls.delivery = Partner.create(
            {"name": "Del", "parent_id": cls.company.id, "type": "delivery"}
        )
        cls.contact = Partner.create(
            {"name": "Con", "parent_id": cls.company.id, "type": "contact"}
        )

    def test_billing_domain_selects_invoice_and_self(self):
        found = self.env["res.partner"].search(
            self.company._get_billing_address_domain()
        )

        self.assertIn(self.invoice, found)
        self.assertIn(self.company, found, "the commercial partner itself qualifies")
        self.assertNotIn(self.delivery, found)
        self.assertNotIn(self.contact, found)

    def test_billing_domain_matches_what_the_page_used_to_inline(self):
        """Same answer as the hand-written domain it replaced."""
        inlined = self.env["res.partner"].search(
            [
                ("id", "child_of", self.company.ids),
                "|",
                ("type", "in", ["invoice", "other"]),
                ("id", "=", self.company.id),
            ]
        )
        via_hook = self.env["res.partner"].search(
            self.company._get_billing_address_domain()
        )

        self.assertEqual(inlined, via_hook)


@tagged("-at_install", "post_install")
class TestAddressCompleteness(TransactionCase):
    """``_has_all_address_fields`` replaced an ``all(read().values())``."""

    def test_id_is_no_longer_part_of_the_answer(self):
        """``read()`` always returns ``id``, which is true by construction.

        A partner missing every mandatory field must answer False; under the old
        idiom the always-true ``id`` key sat in the same ``all()``.
        """
        from odoo.addons.portal.controllers.portal import CustomerPortal

        partner = self.env["res.partner"].create({"name": "Incomplete"})

        self.assertFalse(
            CustomerPortal()._has_all_address_fields(partner, {"street", "city"})
        )

    def test_complete_partner_passes(self):
        from odoo.addons.portal.controllers.portal import CustomerPortal

        partner = self.env["res.partner"].create(
            {"name": "Complete", "street": "1 St", "city": "Brussels"}
        )

        self.assertTrue(
            CustomerPortal()._has_all_address_fields(partner, {"street", "city"})
        )

    def test_empty_partner_is_not_complete(self):
        from odoo.addons.portal.controllers.portal import CustomerPortal

        self.assertFalse(
            CustomerPortal()._has_all_address_fields(
                self.env["res.partner"], {"street"}
            )
        )
