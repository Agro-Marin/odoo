from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_canned_response")
class TestMailCannedResponse(MailCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.canned_responses = cls.env["mail.canned.response"].create(
            [
                {"source": "hello", "substitution": "Hello, how may I help you?"},
                {"source": "bye", "substitution": "Goodbye, have a nice day!"},
            ]
        )

    def test_copy_marks_the_shortcut_as_a_copy(self) -> None:
        """`source` is the shortcut the user types, so two identical ones are
        indistinguishable in the list and in the composer's `::` menu."""
        copies = self.canned_responses.copy()
        self.assertEqual(copies.mapped("source"), ["hello (copy)", "bye (copy)"])
        self.assertEqual(
            copies.mapped("substitution"),
            self.canned_responses.mapped("substitution"),
        )

    def test_copy_honours_an_explicit_source(self) -> None:
        """An explicit `source` in `default` wins over the suffix."""
        copy = self.canned_responses[0].copy({"source": "howdy"})
        self.assertEqual(copy.source, "howdy")
