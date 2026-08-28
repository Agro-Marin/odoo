from odoo import Command
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestBaseTaxDisplayName(BaseTaxCommon):
    def _type_tax_use_label(self, tax, value):
        return dict(tax._fields["type_tax_use"]._description_selection(self.env))[value]

    def test_display_name_plain(self):
        tax = self._tax(21.0, name="VAT 21")
        self.assertEqual(tax.display_name, "VAT 21")

    def test_display_name_appends_selected_field(self):
        tax = self._tax(21.0, name="VAT 21", type_tax_use="sale")
        label = self._type_tax_use_label(tax, "sale")
        self.assertEqual(
            tax.with_context(append_fields=["type_tax_use"]).display_name,
            f"VAT 21 ({label})",
        )

    def test_display_name_formatted_uses_markdown_wrapper(self):
        tax = self._tax(21.0, name="VAT 21", type_tax_use="sale")
        formatted = tax.with_context(
            formatted_display_name=True, append_fields=["type_tax_use"]
        ).display_name
        label = self._type_tax_use_label(tax, "sale")
        self.assertIn(f"\t--{label}--", formatted)

    def test_display_name_appends_country_code_on_mismatch(self):
        other = self.env["res.country"].search(
            [("id", "!=", self.country.id), ("code", "!=", False)], limit=1
        )
        group = self.env["account.tax.group"].create(
            {
                "name": "other-country group",
                "company_ids": [Command.set(self.company.ids)],
                "country_id": other.id,
            }
        )
        tax = self._tax(21.0, name="VAT X", country_id=other.id, tax_group_id=group.id)
        self.assertEqual(tax.display_name, f"VAT X ({other.code})")
