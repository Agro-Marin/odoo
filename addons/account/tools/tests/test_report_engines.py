import unittest

from addons.account.tools.report_engines import (
    AccountCodesFormulaError,
    AccountCodesTerm,
    parse_account_codes_formula,
)


class ParseAccountCodesFormulaTest(unittest.TestCase):
    def test_terms_carry_sign_prefix_exclusions_and_balance_side(self):
        self.assertEqual(
            parse_account_codes_formula(r"-10\(101,102)C + 20D+tag(account.tag_x)"),
            [
                AccountCodesTerm(-1, "10", ("101", "102"), "C", None, None),
                AccountCodesTerm(1, "20", (), "D", None, None),
                AccountCodesTerm(
                    1, "tag(account.tag_x)", (), "", "account.tag_x", None
                ),
            ],
        )

    def test_numeric_tag_prefix_resolves_to_an_id(self):
        (term,) = parse_account_codes_formula("tag(42)")
        self.assertTrue(term.is_tag)
        self.assertEqual(term.tag_id, 42)

    def test_invalid_token_is_reported(self):
        with self.assertRaises(AccountCodesFormulaError) as caught:
            parse_account_codes_formula("10+#")
        self.assertEqual(caught.exception.token, "+#")

    def test_matching_honours_exclusions_before_prefix_or_tag(self):
        (code_term,) = parse_account_codes_formula(r"40\(401)")
        self.assertTrue(code_term.matches_account("400100", [], None))
        self.assertFalse(code_term.matches_account("401000", [], None))
        self.assertFalse(code_term.matches_account("500000", [], None))

        (tag_term,) = parse_account_codes_formula(r"tag(7)\(9)")
        self.assertTrue(tag_term.matches_account("100000", [7], 7))
        self.assertFalse(tag_term.matches_account("900000", [7], 7))
        self.assertFalse(tag_term.matches_account("100000", [8], 7))
