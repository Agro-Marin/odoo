"""Negative tests for the ``account.tax`` constraints shipped by ``base_tax``.

Every ``@api.constrains`` raise-branch of the model gets its discriminating
case: name uniqueness, tax-group country consistency, repartition-line
structure, and children-taxes topology.
"""

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestAccountTaxConstraints(BaseTaxCommon):
    # ------------------------------------------------------------------
    # _constrains_name
    # ------------------------------------------------------------------
    def test_duplicate_name_rejected(self):
        """Two taxes with the same name/type/scope/country must be rejected."""
        self._tax(10.0, name="BT unique tax")
        with self.assertRaises(ValidationError):
            self._tax(21.0, name="BT unique tax")

    def test_duplicate_name_allowed_for_type_none(self):
        """type_tax_use='none' taxes are exempt from the uniqueness check."""
        self._tax(10.0, name="BT none-type tax", type_tax_use="none")
        tax = self._tax(21.0, name="BT none-type tax", type_tax_use="none")
        self.assertEqual(tax.name, "BT none-type tax")

    # ------------------------------------------------------------------
    # _validate_tax_group_id
    # ------------------------------------------------------------------
    def test_tax_group_country_mismatch_rejected(self):
        """A tax cannot use a group pinned to a different country."""
        other_country = self.env.ref("base.fr")
        if self.country == other_country:
            other_country = self.env.ref("base.us")
        foreign_group = self.env["account.tax.group"].create(
            {
                "name": "BT foreign group",
                "company_id": self.company.id,
                "country_id": other_country.id,
            }
        )
        with self.assertRaises(ValidationError):
            self._tax(10.0, tax_group_id=foreign_group.id)

    # ------------------------------------------------------------------
    # _validate_repartition_lines / _check_repartition_lines
    # ------------------------------------------------------------------
    def test_repartition_line_count_mismatch_rejected(self):
        """Invoice and refund distributions must have the same number of lines."""
        tax = self._tax(10.0)
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.create(
                            {"repartition_type": "tax", "factor_percent": 50.0}
                        )
                    ]
                }
            )

    def test_repartition_second_base_line_rejected(self):
        """Each distribution must contain exactly one base line."""
        tax = self._tax(10.0)
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.create({"repartition_type": "base"})
                    ],
                    "refund_repartition_line_ids": [
                        Command.create({"repartition_type": "base"})
                    ],
                }
            )

    def test_repartition_factor_mismatch_rejected(self):
        """Invoice and refund tax lines must match percentages pairwise."""
        tax = self._tax(10.0)
        invoice_tax_line = tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.update(invoice_tax_line.id, {"factor_percent": 50.0})
                    ]
                }
            )

    def test_repartition_total_factor_not_100_rejected(self):
        """Matching invoice/refund factors still need a +100% total."""
        tax = self._tax(10.0)
        invoice_tax_line = tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        refund_tax_line = tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        with self.assertRaises(ValidationError):
            tax.write(
                {
                    "invoice_repartition_line_ids": [
                        Command.update(invoice_tax_line.id, {"factor_percent": 50.0})
                    ],
                    "refund_repartition_line_ids": [
                        Command.update(refund_tax_line.id, {"factor_percent": 50.0})
                    ],
                }
            )

    # ------------------------------------------------------------------
    # _check_children_scope
    # ------------------------------------------------------------------
    def test_group_child_with_other_type_rejected(self):
        """A group's children must share its type_tax_use (or use 'none')."""
        child = self._tax(10.0, type_tax_use="purchase")
        with self.assertRaises(ValidationError):
            self._tax(
                0.0,
                amount_type="group",
                type_tax_use="sale",
                children_tax_ids=[Command.set(child.ids)],
            )

    def test_nested_group_rejected(self):
        """A group of taxes cannot contain another group."""
        leaf = self._tax(10.0)
        inner_group = self._tax(
            0.0, amount_type="group", children_tax_ids=[Command.set(leaf.ids)]
        )
        with self.assertRaises(ValidationError):
            self._tax(
                0.0,
                amount_type="group",
                children_tax_ids=[Command.set(inner_group.ids)],
            )

    def test_tax_self_recursion_rejected(self):
        """A tax cannot be (transitively) its own child."""
        leaf = self._tax(10.0)
        group = self._tax(
            0.0, amount_type="group", children_tax_ids=[Command.set(leaf.ids)]
        )
        with self.assertRaises(ValidationError):
            group.write({"children_tax_ids": [Command.link(group.id)]})
