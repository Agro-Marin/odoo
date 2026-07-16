# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo.tests import BaseCase, tagged

from odoo.addons.payment.logging import SensitiveDataFilter


@tagged("-at_install", "post_install")
class TestSensitiveDataFilter(BaseCase):
    """DB-free unit tests for the payment logging `SensitiveDataFilter`."""

    def _make_record(self, args):
        # Set `args` directly to mirror the real logging pipeline (and the filter itself), bypassing
        # `LogRecord`'s single-Mapping-arg special case.
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
        record.args = args
        return record

    def test_empty_keys_is_a_noop(self):
        """Test that a filter without sensitive keys leaves the record's args untouched."""
        filter_ = SensitiveDataFilter(set())
        args = {"card_number": "4242424242424242", "amount": 10}
        record = self._make_record(args)
        self.assertTrue(filter_.filter(record))
        # The exact same object is kept: no recursive rebuild happens when there is nothing to mask.
        self.assertIs(record.args, args)

    def test_masks_dict_values_by_key(self):
        """Test that values whose key is sensitive are redacted in dict args."""
        filter_ = SensitiveDataFilter({"card_number"})
        record = self._make_record({"card_number": "4242424242424242", "amount": 10})
        filter_.filter(record)
        self.assertEqual(record.args["card_number"], "[REDACTED]")
        self.assertEqual(record.args["amount"], 10)

    def test_masks_sensitive_value_in_string(self):
        """Test that a JSON-like sensitive value embedded in a string is redacted."""
        filter_ = SensitiveDataFilter({"card_number"})
        record = self._make_record(('{"card_number": "4242424242424242"}',))
        filter_.filter(record)
        self.assertIn('"card_number": "[REDACTED]"', record.args[0])
        self.assertNotIn("4242424242424242", record.args[0])

    def test_key_with_regex_metacharacters_does_not_break(self):
        """Test that a key containing regex metacharacters is escaped and does not raise."""
        # `re.escape` protects against metacharacters in the key; without it this would raise while
        # compiling the pattern or match the wrong text.
        filter_ = SensitiveDataFilter({"a.b[c]"})
        record = self._make_record(('{"a.b[c]": "secret"}',))
        filter_.filter(record)
        self.assertIn("[REDACTED]", record.args[0])
        self.assertNotIn("secret", record.args[0])

    def test_added_key_recompiles_patterns(self):
        """Test that mutating the shared keys set after construction updates the masking."""
        keys = set()
        filter_ = SensitiveDataFilter(keys)
        keys.add("token")  # A provider module may populate the shared `SENSITIVE_KEYS` set.
        record = self._make_record({"token": "abc"})
        filter_.filter(record)
        self.assertEqual(record.args["token"], "[REDACTED]")
