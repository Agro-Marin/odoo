from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartnerBarcodeUnicity(TransactionCase):
    """RP-L1: res.partner.barcode is company_dependent (per-company jsonb), so
    uniqueness is scoped per company and the ir.default fallback value must not
    be mistaken for an explicit barcode.
    """

    def test_fallback_default_is_not_a_false_positive(self):
        # With a non-empty barcode ir.default, partners without an explicit
        # barcode inherit the fallback. Creating another partner whose EXPLICIT
        # barcode equals that fallback must succeed; before the fix the
        # COALESCE-resolved search counted the fallback-only partners as
        # duplicates and raised spuriously.
        self.env["ir.default"].set("res.partner", "barcode", "FALLBACK")
        Partner = self.env["res.partner"]
        Partner.create({"name": "rpl1 no-barcode"})  # inherits the fallback
        Partner.create(
            {"name": "rpl1 explicit", "barcode": "FALLBACK"}
        )  # must not raise

    def test_same_company_duplicate_rejected(self):
        company = self.env["res.company"].create({"name": "RP-L1 same"})
        Partner = self.env["res.partner"].with_company(company)
        Partner.create({"name": "rpl1 p1", "barcode": "DUP"})
        with self.assertRaises(ValidationError):
            Partner.create({"name": "rpl1 p2", "barcode": "DUP"})

    def test_cross_company_same_barcode_allowed(self):
        c1, c2 = self.env["res.company"].create(
            [{"name": "RP-L1 c1"}, {"name": "RP-L1 c2"}]
        )
        Partner = self.env["res.partner"]
        p1 = Partner.create({"name": "rpl1 cc1"})
        p2 = Partner.create({"name": "rpl1 cc2"})
        p1.with_company(c1).barcode = "SHARED"
        # Different company slot -> the same barcode must be allowed.
        p2.with_company(c2).barcode = "SHARED"
        self.assertEqual(p1.with_company(c1).barcode, "SHARED")
        self.assertEqual(p2.with_company(c2).barcode, "SHARED")
