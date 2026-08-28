from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAccountIncoterms(TransactionCase):
    """The dropdown shows ``[EXW] EX WORKS``, so the code has to be typeable."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.incoterms = cls.env["account.incoterms"]
        cls.exw = cls.env.ref("account.incoterm_EXW")

    def test_name_search_matches_the_code(self):
        found = self.incoterms.name_search("EXW")
        self.assertIn(
            self.exw.id,
            [incoterm_id for incoterm_id, _display_name in found],
            "Typing an incoterm code must find it: the code is what the "
            "dropdown displays, and none of the shipped incoterms repeat it "
            "inside their name.",
        )

    def test_name_search_still_matches_the_name(self):
        found = self.incoterms.name_search("EX WORKS")
        self.assertIn(
            self.exw.id, [incoterm_id for incoterm_id, _display_name in found]
        )

    def test_name_search_is_case_insensitive_on_the_code(self):
        found = self.incoterms.name_search("exw")
        self.assertIn(
            self.exw.id, [incoterm_id for incoterm_id, _display_name in found]
        )
