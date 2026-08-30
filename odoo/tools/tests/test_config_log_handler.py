import unittest

from odoo.tools.config import _deduplicate_loggers


class TestLogHandlerSpecs(unittest.TestCase):
    def test_last_spelling_of_a_logger_wins(self):
        self.assertEqual(
            list(_deduplicate_loggers(["odoo:INFO", "werkzeug:WARNING", "odoo:DEBUG"])),
            ["odoo:DEBUG", "werkzeug:WARNING"],
        )

    def test_an_empty_module_is_the_root_logger_and_is_valid(self):
        self.assertEqual(list(_deduplicate_loggers([":INFO"])), [":INFO"])

    def test_a_spec_with_no_level_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            list(_deduplicate_loggers(["odoo.orm"]))
        self.assertIn("odoo.orm", str(caught.exception))
        self.assertIn("MODULE:LEVEL", str(caught.exception))

    def test_one_bad_spec_does_not_pass_as_the_others_succeeding(self):
        with self.assertRaises(ValueError):
            list(_deduplicate_loggers(["odoo.orm", "odoo:INFO"]))
