import unittest

from odoo.tools.config import _deduplicate_loggers


class TestDeduplicateLoggers(unittest.TestCase):
    def test_refuses_a_malformed_token_without_colon(self):
        # This used to assert `== []`.  The drop was deliberate -- init_logger
        # does `name, level = item.split(":")` and would raise on a bare name --
        # but it made `--log-handler werkzeug` a flag that does nothing and says
        # nothing, against a metavar reading MODULE:LEVEL.  Every other
        # malformed value in this module reaches parser.error; so does this one
        # now.  test_config_log_handler.py carries the rest of the contract.
        with self.assertRaises(ValueError):
            list(_deduplicate_loggers(["werkzeug"]))

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
