from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDecimalPrecisionAudit(TransactionCase):
    def test_negative_digits_rejected_on_create(self):
        with self.assertRaises(ValidationError):
            self.env["decimal.precision"].create(
                {"name": "audit_dp_negative_create", "digits": -1}
            )

    def test_negative_digits_rejected_on_write(self):
        precision = self.env["decimal.precision"].create(
            {"name": "audit_dp_negative_write", "digits": 2}
        )
        with self.assertRaises(ValidationError):
            precision.write({"digits": -1})

    def test_precision_get_unknown_application_warns(self):
        Precision = self.env["decimal.precision"]
        name = "audit_dp_unknown_application"
        self.env.registry.clear_cache("stable")
        with self.assertLogs(
            "odoo.addons.base.models.decimal_precision", "WARNING"
        ) as capture:
            self.assertEqual(Precision.precision_get(name), 2)
        self.assertIn(name, capture.output[0])

    def test_precision_get_reflects_write(self):
        Precision = self.env["decimal.precision"]
        name = "audit_dp_cache"
        precision = Precision.create({"name": name, "digits": 2})
        self.assertEqual(Precision.precision_get(name), 2)
        precision.write({"digits": 5})
        self.assertEqual(Precision.precision_get(name), 5)
