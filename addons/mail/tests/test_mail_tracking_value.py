from unittest.mock import patch

from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install", "mail_track")
class TestMailTrackingValue(MailCommon):
    """`mail.tracking.value` stores the company of a company dependent field.

    A real company dependent *and* tracked field only exists in downstream
    addons (`account.product_category.property_account_income_categ_id`,
    `stock_account.product.property_valuation`), which `mail` cannot install, and
    `ir.model.fields` has no `company_dependent` column so one cannot be created
    at runtime. These tests therefore drive the tracking pipeline with the
    `col_info` that `fields_get()` returns for such a field.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Tracked Partner"})
        cls.other_company = cls.env["res.company"].create({"name": "Other Company"})

    def _col_info(self, fname, company_dependent=False):
        col_info = self.partner.fields_get(
            [fname],
            attributes=(
                "string",
                "type",
                "selection",
                "currency_field",
                "company_dependent",
            ),
        )[fname]
        col_info["company_dependent"] = company_dependent
        return col_info

    def test_company_dependent_field_records_its_company(self):
        values = self.env["mail.tracking.value"]._create_tracking_values(
            False,
            "new",
            "function",
            self._col_info("function", True),
            self.partner,
        )
        self.assertEqual(values["company_id"], self.env.company.id)

    def test_company_dependent_field_records_the_active_company(self):
        """The company stored is the one the value was written in, not the main one."""
        env = self.env(
            context=dict(
                self.env.context,
                allowed_company_ids=[
                    self.other_company.id,
                    self.env.company.id,
                ],
            )
        )
        values = (
            env["mail.tracking.value"]
            .with_company(self.other_company)
            ._create_tracking_values(
                False,
                "new",
                "function",
                self._col_info("function", True),
                self.partner,
            )
        )
        self.assertEqual(values["company_id"], self.other_company.id)

    def test_plain_field_records_no_company(self):
        values = self.env["mail.tracking.value"]._create_tracking_values(
            False,
            "new",
            "function",
            self._col_info("function"),
            self.partner,
        )
        self.assertNotIn("company_id", values)

    def test_message_track_asks_the_orm_for_company_dependent(self):
        """Without the attribute in `fields_get`, `col_info` never carries the flag."""
        Partner = type(self.env["res.partner"])
        original = Partner.fields_get
        seen = []

        def spy(records, allfields=None, attributes=None):
            seen.append(attributes)
            return original(records, allfields, attributes)

        self.partner.function = "changed"
        with patch.object(Partner, "fields_get", spy):
            self.partner._message_track(
                ["function"], {self.partner.id: {"function": False}}
            )
        self.assertTrue(seen, "_message_track did not call fields_get")
        self.assertIn("company_dependent", seen[0])
