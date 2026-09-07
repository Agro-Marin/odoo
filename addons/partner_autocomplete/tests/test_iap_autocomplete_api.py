from unittest.mock import patch

from odoo import modules
from odoo.tests import TransactionCase, tagged

from odoo.addons.iap.tools.iap_tools import InsufficientCreditError


@tagged("post_install", "-at_install")
class TestIapAutocompleteApi(TransactionCase):
    def test_request_during_tests_does_not_report_insufficient_credit(self):
        """A call made while `current_test` is set (i.e. any real Odoo test
        run) must not be mislabeled as an "Insufficient Credit" failure - that
        string is reserved for a real `InsufficientCreditError` from the IAP
        server. Deliberately do NOT mock `_contact_iap` here, so the real
        method body runs and falls through to `iap_jsonrpc`'s own test-mode
        guard.
        """
        self.assertTrue(modules.module.current_test, "expected to run inside a test")
        response, error = self.env[
            "iap.autocomplete.api"
        ]._request_partner_autocomplete(
            "search_by_name", {"query": "x", "query_country_code": "US"}
        )
        self.assertFalse(response)
        self.assertNotEqual(error, "Insufficient Credit")

    def test_request_reports_real_insufficient_credit(self):
        """A genuine `InsufficientCreditError` from the IAP server is still
        reported as "Insufficient Credit" - only the redundant test-mode
        mislabeling was removed.
        """
        with patch.object(
            type(self.env["iap.autocomplete.api"]),
            "_contact_iap",
            side_effect=InsufficientCreditError("no credit"),
        ):
            response, error = self.env[
                "iap.autocomplete.api"
            ]._request_partner_autocomplete(
                "search_by_name", {"query": "x", "query_country_code": "US"}
            )
        self.assertFalse(response)
        self.assertEqual(error, "Insufficient Credit")
