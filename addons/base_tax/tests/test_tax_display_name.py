"""Regression tests for ``account.tax`` display-name composition (base_tax).

``_compute_display_name`` appends context-driven suffixes to the tax name
(selected fields, a markdown wrapper, and the country code when the tax country
differs from the company fiscal country). None of these branches were exercised
standalone.
"""

from odoo import Command
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestBaseTaxDisplayName(BaseTaxCommon):
    def _type_tax_use_label(self, tax, value):
        return dict(tax._fields["type_tax_use"]._description_selection(self.env))[value]

    def test_display_name_plain(self):
        """With no context flags and a matching country, the name is unchanged."""
        tax = self._tax(21.0, name="VAT 21")
        self.assertEqual(tax.display_name, "VAT 21")

    def test_display_name_appends_selected_field(self):
        """``append_fields`` adds the human label of the requested field."""
        tax = self._tax(21.0, name="VAT 21", type_tax_use="sale")
        label = self._type_tax_use_label(tax, "sale")
        self.assertEqual(
            tax.with_context(append_fields=["type_tax_use"]).display_name,
            f"VAT 21 ({label})",
        )

    def test_display_name_formatted_uses_markdown_wrapper(self):
        """``formatted_display_name`` switches the suffix wrapper to markdown."""
        tax = self._tax(21.0, name="VAT 21", type_tax_use="sale")
        formatted = tax.with_context(
            formatted_display_name=True, append_fields=["type_tax_use"]
        ).display_name
        label = self._type_tax_use_label(tax, "sale")
        self.assertIn(f"\t--{label}--", formatted)

    def test_display_name_appends_country_code_on_mismatch(self):
        """A tax whose country differs from the company country gets the code suffix."""
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
