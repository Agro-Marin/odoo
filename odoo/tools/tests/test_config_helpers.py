import unittest

from odoo.tools.config import _deduplicate_loggers


class TestDeduplicateLoggers(unittest.TestCase):
    def test_skips_malformed_token_without_colon(self):
        self.assertEqual(list(_deduplicate_loggers(["werkzeug"])), [])

    def test_dedup_last_value_wins(self):
        self.assertEqual(
            list(_deduplicate_loggers(["a:INFO", "a:DEBUG", "b:WARNING"])),
            ["a:DEBUG", "b:WARNING"],
        )

    def test_dotted_logger_name_preserved(self):
        self.assertEqual(
            list(_deduplicate_loggers(["odoo.foo:DEBUG"])), ["odoo.foo:DEBUG"]
        )


if __name__ == "__main__":
    unittest.main()
