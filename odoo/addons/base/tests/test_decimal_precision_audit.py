"""Audit tests for decimal.precision (DP-C1 negative-digits constraint, DP-T1 cache).

DP-C1 covers the @api.constrains("digits") guard that rejects negative precisions.
DP-T1 verifies that writing a new digits value clears the ormcache so precision_get
returns the fresh value.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDecimalPrecisionAudit(TransactionCase):
    """Constraint and cache-invalidation behaviour of decimal.precision."""

    def test_negative_digits_rejected_on_create(self):
        """DP-C1: creating a precision with negative digits raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["decimal.precision"].create(
                {"name": "audit_dp_negative_create", "digits": -1}
            )

    def test_negative_digits_rejected_on_write(self):
        """DP-C1: writing a negative digits value raises ValidationError."""
        precision = self.env["decimal.precision"].create(
            {"name": "audit_dp_negative_write", "digits": 2}
        )
        with self.assertRaises(ValidationError):
            precision.write({"digits": -1})

    def test_precision_get_reflects_write(self):
        """DP-T1: write clears the ormcache, so precision_get returns the new value."""
        Precision = self.env["decimal.precision"]
        name = "audit_dp_cache"
        precision = Precision.create({"name": name, "digits": 2})
        # Prime the cache, then change the value and confirm the cached accessor
        # reflects the update (the write override clears the "stable" cache).
        self.assertEqual(Precision.precision_get(name), 2)
        precision.write({"digits": 5})
        self.assertEqual(Precision.precision_get(name), 5)
