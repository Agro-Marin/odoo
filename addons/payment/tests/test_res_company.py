from odoo.tests import tagged

from odoo.addons.payment.tests.common import PaymentCommon


@tagged("-at_install", "post_install")
class TestResCompany(PaymentCommon):
    def test_creating_company_duplicates_providers(self):
        """Ensure that installed payment providers of an existing company are correctly duplicated
        when a new company is created."""
        main_company = self.env.company
        main_company_providers_count = self.env["payment.provider"].search_count(
            [
                ("company_id", "=", main_company.id),
                ("module_state", "=", "installed"),
            ]
        )

        new_company = self.env["res.company"].create({"name": "New Company"})
        new_company_providers_count = self.env["payment.provider"].search_count(
            [
                ("company_id", "=", new_company.id),
                ("module_state", "=", "installed"),
            ]
        )

        self.assertEqual(new_company_providers_count, main_company_providers_count)

    def test_creating_company_without_custom_mode_in_registry(self):
        """Company creation must not require payment_custom's custom_mode field.

        payment can be installed without payment_custom (e.g. pulled in as a
        dependency of account_payment): provider duplication must then skip
        the custom-mode filtering instead of raising KeyError. Only a registry
        without payment_custom exercises the absent-field branch — the
        payment-only test database does; a full database does not.
        """
        company = self.env["res.company"].create({"name": "No Custom Mode Company"})
        self.assertTrue(company.exists())
