"""Regression tests for the ways scanned input used to reach a 500.

`parse_barcode` is reachable over RPC by any internal user and its argument is
whatever came off a scanner, so a malformed barcode has to be a parse failure --
never an exception, and never unbounded work.
"""

from odoo.exceptions import ValidationError
from odoo.tests import common


class TestBarcodeHardening(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.nomenclature = cls.env["barcode.nomenclature"].create(
            {"name": "Hardening Test"}
        )

    def _add_rule(self, **vals):
        return self.env["barcode.rule"].create(
            {
                "name": "Rule",
                "barcode_nomenclature_id": self.nomenclature.id,
                "encoding": "any",
                "type": "product",
                **vals,
            }
        )

    def test_malformed_uri_is_a_parse_failure(self):
        """A URI that cannot be decoded returns [], it does not raise.

        Every one of these used to raise ValueError out of a bare tuple unpack,
        surfacing as an HTTP 500 with a traceback.
        """
        for barcode in (
            "urn:epc:id:sgtin:4012345.012345",  # too few fields
            "urn:epc:id:sgtin:4012345.012345.99.88",  # too many fields
            "urn:epc:id:sscc:952656789012",  # too few fields
            "urn:epc:id:giai:4012345.999887",  # unknown identifier
            "urn:",  # not five ':'-separated parts
            "urn:epc:id:sscc:abcdefghijkl.03456",  # non-digit company prefix
        ):
            with self.subTest(barcode=barcode):
                self.assertEqual(self.nomenclature.parse_barcode(barcode), [])

    def test_non_digit_numeric_slot_is_a_parse_failure(self):
        """A numeric slot that is not ASCII digits does not raise.

        `str.isdigit` accepts numerals `int()` rejects, so a barcode carrying
        e.g. '²' used to raise ValueError from inside the match.
        """
        self._add_rule(pattern="21{NNDDD}")
        for barcode in ("21²²²²²", "21123ab", "2112", "21"):
            with self.subTest(barcode=barcode):
                result = self.nomenclature.parse_barcode(barcode)
                self.assertEqual(result["type"], "error")
                self.assertEqual(result["value"], 0)
        self.assertEqual(self.nomenclature.parse_barcode("2112345")["value"], 12.345)

    def test_catastrophic_pattern_is_rejected(self):
        """A pattern that nests repetitions is refused on write.

        Patterns run on every scan; `(x+x+)+y` against a 60-character barcode
        pinned a core for minutes, and the client disconnecting did not stop it.
        """
        for pattern in (
            "(x+x+)+y",
            "(a+)*",
            "(?:a+)+",
            "([a-z]+)*$",
            "(\\d{2,})+",
            "(a|aa)+$",
        ):
            with self.subTest(pattern=pattern), self.assertRaises(ValidationError):
                self._add_rule(pattern=pattern)

    def test_ordinary_patterns_are_still_accepted(self):
        """The guard must not reject the patterns real nomenclatures use."""
        for pattern in (
            ".*",
            "^[0-9]+$",
            "21.....{NNDDD}",
            "23.....{NNNDD}",
            "22{NN}",
            "(A|B)+",
            "O-BTN.pack",
            "414",
        ):
            with self.subTest(pattern=pattern):
                self.assertTrue(self._add_rule(pattern=pattern))

    def test_oversized_barcode_is_not_matched(self):
        """The regex subject is bounded, whatever the pattern."""
        self._add_rule(pattern=".*")
        result = self.nomenclature.parse_barcode("x" * 5000)
        self.assertEqual(result["type"], "error")

    def test_parse_barcode_refuses_multiple_nomenclatures(self):
        """Parsing across a union of rule sets is a caller error, not a result."""
        other = self.env["barcode.nomenclature"].create({"name": "Other"})
        with self.assertRaises(ValueError):
            (self.nomenclature | other).parse_barcode("12345670")

    def test_alias_rule_requires_an_alias(self):
        with self.assertRaises(ValidationError):
            self._add_rule(type="alias", pattern="^AAA", alias=False)


class TestBarcodeSessionInfo(common.TransactionCase):
    """`session_info` is on the critical path of every backend page load.

    An administrator who cleared the parameter in the UI stored an empty
    string -- which `get_param`'s default does not cover -- and every internal
    user got an HTTP 500 on /odoo until someone guessed why.
    """

    def _max_time(self, raw):
        self.env["ir.config_parameter"].sudo().set_param(
            "barcode.max_time_between_keys_in_ms", raw
        )
        return self.env["ir.http"]._get_max_time_between_keys()

    def test_invalid_parameter_falls_back(self):
        for raw in ("", "fast", "150.5", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(self._max_time(raw), 150)

    def test_out_of_range_parameter_is_floored(self):
        for raw in ("0", "-5"):
            with self.subTest(raw=raw):
                self.assertEqual(self._max_time(raw), 1)

    def test_valid_parameter_is_used(self):
        self.assertEqual(self._max_time("  220  "), 220)

    def test_absent_parameter_uses_the_default(self):
        self.env["ir.config_parameter"].sudo().search(
            [("key", "=", "barcode.max_time_between_keys_in_ms")]
        ).unlink()
        self.assertEqual(self.env["ir.http"]._get_max_time_between_keys(), 150)
