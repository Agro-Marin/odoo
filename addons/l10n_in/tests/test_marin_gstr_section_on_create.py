from datetime import date

from odoo import Command
from odoo.addons.l10n_in.tests.common import L10nInTestInvoicingCommon
from odoo.tests import tagged

TEST_DATE = date(2025, 6, 8)


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestMarinGstrSectionOnCreate(L10nInTestInvoicingCommon):
    """The section must be set by the create() itself.

    Every other GSTR test builds its invoice through `_init_inv`, which writes
    `line_vals` and/or posts before asserting -- and that later write is what used
    to set the section. An invoice created in one call and left in draft carried
    no classification at all, which is invisible to a suite that always writes.
    """

    def _create_invoice_in_one_call(self):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_b.id,
            'invoice_date': TEST_DATE,
            'invoice_line_ids': [Command.create({
                'product_id': self.product_a.id,
                'price_unit': 1000,
                'quantity': 1,
                'tax_ids': [Command.set(self.tax_sale_a.ids)],
            })],
        })

    def test_gstr_section_is_set_without_any_write_after_create(self):
        invoice = self._create_invoice_in_one_call()
        classified = invoice.line_ids.filtered(
            lambda line: line.display_type in ('product', 'tax')
        )
        self.assertTrue(classified)
        self.assertFalse(
            classified.filtered(lambda line: not line.l10n_in_gstr_section),
            "create() alone must classify the lines; the sync container is empty "
            "when the stack is built, so the section can only be read on unwind",
        )

    def test_gstr_section_survives_a_reload_from_the_database(self):
        invoice = self._create_invoice_in_one_call()
        invoice.invalidate_recordset()
        invoice.line_ids.invalidate_recordset()
        classified = invoice.line_ids.filtered(
            lambda line: line.display_type in ('product', 'tax')
        )
        self.assertFalse(
            classified.filtered(lambda line: not line.l10n_in_gstr_section),
            "the section must be persisted, not only present in cache",
        )
