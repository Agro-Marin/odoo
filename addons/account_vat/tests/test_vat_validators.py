"""Tests for the country-specific VAT validators and dispatch."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVatValidators(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]

    def test_split_vat_with_country_prefix(self):
        """A country prefix is split off the number part."""
        self.assertEqual(self.Partner._split_vat("BE0477472701"), ("BE", "0477472701"))

    def test_split_vat_without_prefix(self):
        """A number with no alpha prefix is returned whole (boundary)."""
        self.assertEqual(self.Partner._split_vat("0477472701"), ("", "0477472701"))

    def test_check_vat_mx_valid_rfc(self):
        """A well-formed Mexican RFC with a valid embedded date passes."""
        # AAA + 010101 (2001-01-01) + 3-char homoclave.
        self.assertTrue(self.Partner.check_vat_mx("AAA010101AAA"))

    def test_check_vat_mx_bad_date_rejected(self):
        """An RFC whose embedded date is impossible is rejected (negative)."""
        # month 13 does not exist.
        self.assertFalse(self.Partner.check_vat_mx("AAA011301AAA"))

    def test_check_vat_mx_bad_format_rejected(self):
        """An RFC that does not match the pattern is rejected (negative)."""
        self.assertFalse(self.Partner.check_vat_mx("not-an-rfc"))

    def test_check_vat_number_dispatches_to_country(self):
        """_check_vat_number routes to the country-specific validator."""
        self.assertTrue(self.Partner._check_vat_number("mx", "AAA010101AAA"))
        self.assertFalse(self.Partner._check_vat_number("mx", "AAA011301AAA"))

    def test_check_vat_number_unknown_country_passes(self):
        """A country with no validator and no stdnum module passes (boundary)."""
        self.assertTrue(self.Partner._check_vat_number("zz", "whatever"))

    # ------------------------------------------------------------------
    # Fork-specific branches: the escape hatches and TIN formats this fork
    # adds on top of the stdnum delegation. Samples were derived from the
    # algorithms themselves and verified against the running code.
    # ------------------------------------------------------------------

    def test_check_vat_mx_century_mapping(self):
        """The 2-digit year maps to 1900 above 30 and to 2000 below it."""
        # 99 -> 1999, not a leap year, so Feb 29 cannot exist.
        self.assertFalse(self.Partner.check_vat_mx("AAA990229AAA"))
        # 00 -> 2000, a leap year, so the same day is valid.
        self.assertTrue(self.Partner.check_vat_mx("AAA000229AAA"))

    def test_check_vat_mx_accepts_moral_and_separated_forms(self):
        """Four-letter prefixes, enye and separators are all accepted."""
        self.assertTrue(self.Partner.check_vat_mx("ABCD010101AAA"))
        self.assertTrue(self.Partner.check_vat_mx("AÑA010101AAA"))
        self.assertTrue(self.Partner.check_vat_mx("AAA-010101-AAA"))

    def test_check_vat_mx_rejects_malformed(self):
        """A short prefix or trailing junk is rejected (fullmatch)."""
        self.assertFalse(self.Partner.check_vat_mx("AA010101AAA"))
        self.assertFalse(self.Partner.check_vat_mx("AAA010101AAAX"))

    def test_check_vat_ch_mod11_checksum(self):
        """The Swiss number is accepted on its MOD11 check digit only."""
        # digits 12345678 -> MOD11 weighting (5,4,3,2,7,6,5,4) -> check 8
        self.assertTrue(self.Partner.check_vat_ch("E123456788MWST"))
        self.assertTrue(self.Partner.check_vat_ch("E-123.456.788 TVA"))
        self.assertFalse(self.Partner.check_vat_ch("E123456789MWST"))

    def test_check_vat_ch_rejects_english_abbreviation(self):
        """The English 'VAT' suffix is explicitly not valid in Switzerland."""
        self.assertFalse(self.Partner.check_vat_ch("E123456788VAT"))

    def test_check_vat_gr_allows_edi_test_numbers(self):
        """The Greek EDI test numbers bypass the checksum by design."""
        self.assertTrue(self.Partner.check_vat_gr("047747270"))
        self.assertFalse(self.Partner.check_vat_gr("12345"))

    def test_check_vat_gt_allows_edi_test_numbers(self):
        """The Guatemalan EDI test NITs and the Infile range are accepted."""
        self.assertTrue(self.Partner.check_vat_gt("11201220K"))
        self.assertTrue(self.Partner.check_vat_gt("981234567890K"))
        self.assertFalse(self.Partner.check_vat_gt("123"))

    def test_check_vat_ro_natural_person_tins(self):
        """Romanian natural-person TINs pass alongside the company CUI."""
        # x yy mm dd + 6 digits
        self.assertTrue(self.Partner.check_vat_ro("1900101123456"))
        # the 9000-prefixed form
        self.assertTrue(self.Partner.check_vat_ro("9000123456789"))
        # month 13 matches neither TIN shape nor the CUI checksum
        self.assertFalse(self.Partner.check_vat_ro("1901301123456"))

    def test_check_vat_hu_tin_formats(self):
        """The three Hungarian TIN shapes are accepted."""
        self.assertTrue(self.Partner.check_vat_hu("12345678-1-23"))  # company
        self.assertTrue(self.Partner.check_vat_hu("8123456789"))  # individual
        self.assertTrue(self.Partner.check_vat_hu("12345678"))  # EU 8-digit
        # an individual TIN must start with 8
        self.assertFalse(self.Partner.check_vat_hu("7123456789"))

    def test_check_vat_ec_ruc_length_and_cleaning(self):
        """The Ecuadorian RUC accepts 10 or 13 digits, separators stripped."""
        self.assertTrue(self.Partner.check_vat_ec("1234567890"))
        self.assertTrue(self.Partner.check_vat_ec("1234567890123"))
        self.assertTrue(self.Partner.check_vat_ec("123-456.789 0"))
        self.assertFalse(self.Partner.check_vat_ec("123456789"))

    def test_check_vat_jp_strips_the_t_prefix(self):
        """The Japanese corporate number is accepted with or without its T."""
        self.assertTrue(self.Partner.check_vat_jp("1000000000008"))
        self.assertTrue(self.Partner.check_vat_jp("T1000000000008"))
        self.assertFalse(self.Partner.check_vat_jp("T1000000000009"))

    def test_check_vat_al_requires_ten_characters(self):
        """The Albanian number is length-gated on top of its pattern."""
        self.assertTrue(self.Partner.check_vat_al("K12345678L"))
        self.assertFalse(self.Partner.check_vat_al("K1234567L"))
