from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Published by RENAPO as a sample CURP and used throughout Mexican government
# documentation. Its check digit verifies under the standard algorithm, which
# is what makes it usable as a fixture: a fabricated CURP would only ever
# confirm that the implementation agrees with itself.
VALID_CURP = "HEGG560427MVZRRL04"


@tagged("post_install_l10n", "post_install", "-at_install")
class TestMexicanPartnerIdentifiers(TransactionCase):
    """The identifier kernel's first real consumer.

    Before this, an RFC lived in `res.partner.vat`, a CURP in
    `l10n_mx_edi_curp` (a `Char(size=18)` validated by nothing) and a second
    copy of both on `hr.employee`, checked for length alone. These types put
    the rules in one place and give `_check_<code>` its first use.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.rfc = cls.env.ref("l10n_mx.partner_identifier_type_rfc")
        cls.curp = cls.env.ref("l10n_mx.partner_identifier_type_curp")
        cls.partner = cls.Partner.create(
            {"name": "Contribuyente de Prueba", "country_id": cls.env.ref("base.mx").id}
        )

    def _reject(self, code, value):
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self.partner._update_identifier(code, value)

    def test_the_types_are_seeded_for_mexico(self):
        mexico = self.env.ref("base.mx")

        self.assertEqual(self.rfc.code, "MX_RFC")
        self.assertEqual(self.curp.code, "MX_CURP")
        self.assertIn(mexico, self.rfc.country_ids)
        self.assertIn(mexico, self.curp.country_ids)

    def test_a_tax_id_follows_the_company_and_a_personal_one_does_not(self):
        """The distinction `_synced_commercial_fields` cannot express."""
        self.assertTrue(self.rfc.synced_with_commercial)
        self.assertFalse(self.curp.synced_with_commercial)

    def test_both_rfc_lengths_are_accepted(self):
        """12 for a legal entity, 13 for a natural person."""
        self.partner._update_identifier("MX_RFC", "ABC010101AAA")
        self.assertEqual(self.partner._get_identifier("MX_RFC"), "ABC010101AAA")

        self.partner._update_identifier("MX_RFC", "ABCD010101AAA")
        self.assertEqual(self.partner._get_identifier("MX_RFC"), "ABCD010101AAA")

    def test_the_generic_rfcs_are_accepted(self):
        """The SAT issues these to everyone at once; they must not be refused."""
        for generic in ("XAXX010101000", "XEXX010101000"):
            self.partner._update_identifier("MX_RFC", generic)
            self.assertEqual(self.partner._get_identifier("MX_RFC"), generic)

    def test_an_rfc_whose_date_cannot_exist_is_refused(self):
        self._reject("MX_RFC", "ABCD970231AAA")

    def test_an_rfc_date_is_read_in_either_century(self):
        """29 February is the case a naive range check gets wrong."""
        self.partner._update_identifier("MX_RFC", "ABCD000229AAA")
        self.assertEqual(self.partner._get_identifier("MX_RFC"), "ABCD000229AAA")

        self._reject("MX_RFC", "ABCD010229AAA")

    def test_an_rfc_of_the_wrong_shape_is_refused(self):
        self._reject("MX_RFC", "AB010101AAA")

    def test_a_valid_curp_is_accepted(self):
        self.partner._update_identifier("MX_CURP", VALID_CURP)

        self.assertEqual(self.partner._get_identifier("MX_CURP"), VALID_CURP)

    def test_a_curp_with_the_wrong_check_digit_is_refused(self):
        """What the check digit is for: one mistyped character."""
        self._reject("MX_CURP", VALID_CURP[:17] + "5")

    def test_a_curp_whose_date_cannot_exist_is_refused(self):
        self._reject("MX_CURP", "HEGG561332MVZRRL04")

    def test_a_curp_of_the_wrong_shape_is_refused(self):
        self._reject("MX_CURP", "HEGG560427XVZRRL04")

    def test_the_check_digit_is_the_documented_one(self):
        """Pinned against the published sample, not against our own output."""
        computed = self.curp._curp_check_digit(VALID_CURP[:17])

        self.assertEqual(str(computed), VALID_CURP[17])

    def test_punctuation_does_not_defeat_the_rules(self):
        """Normalization runs first, so a spaced CURP is the same CURP."""
        spaced = f"{VALID_CURP[:4]}-{VALID_CURP[4:10]}-{VALID_CURP[10:]}"

        self.partner._update_identifier("MX_CURP", spaced)

        self.assertEqual(
            self.partner.identifier_ids.filtered(
                lambda i: i.type_id.code == "MX_CURP"
            ).normalized_value,
            VALID_CURP,
        )
