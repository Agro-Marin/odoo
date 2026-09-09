import logging

import odoo.tests
from odoo import Command, fields

from odoo.addons.account.tests.common import AccountTestMockOnlineSyncCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("-at_install", "post_install")
class TestUiReconcile(AccountTestMockOnlineSyncCommon):
    def test_accountant_tour(self):
        self.env.company.write(
            {
                "country_id": None,
                "account_sale_tax_id": None,
                "account_purchase_tax_id": None,
            }
        )

        self.env["account.journal"].create(
            {
                "type": "bank",
                "name": "Empty Bank",
                "code": "EBJ",
            }
        )

        account_with_taxes = self.env["account.account"].search(
            [("tax_ids", "!=", False), ("company_ids", "=", self.env.company.id)]
        )
        account_with_taxes.write(
            {
                "tax_ids": [Command.clear()],
            }
        )
        all_moves = self.env["account.move"].search(
            [("company_id", "=", self.env.company.id), ("move_type", "!=", "entry")]
        )
        all_moves.filtered(
            lambda m: (
                not m.inalterable_hash
                and not m.deferred_move_ids
                and m.state != "draft"
            )
        ).action_draft()
        all_moves.with_context(force_delete=True).unlink()
        bnk = self.env["account.account"].create(
            {
                "code": "X1014",
                "name": "Bank Current Account - (test)",
                "account_type": "asset_cash",
            }
        )
        journal = self.env["account.journal"].create(
            {
                "name": "Bank - Test",
                "code": "TBNK",
                "type": "bank",
                "default_account_id": bnk.id,
            }
        )
        self.env["account.bank.statement.line"].create(
            [
                {
                    "journal_id": journal.id,
                    "amount": 100,
                    "date": fields.Date.today(),
                    "payment_ref": "stl_0001",
                },
                {
                    "journal_id": journal.id,
                    "amount": 200,
                    "date": fields.Date.today(),
                    "payment_ref": "stl_0002",
                },
            ]
        )
        self.env.ref("base.user_admin").write({"email": "mitchell.admin@example.com"})
        self.env["web_tour.tour"].search([]).unlink()

        if not self.env.ref("base.res_partner_2", raise_if_not_found=False):
            demo_partner = self.env["res.partner"].create({"name": "Acme Corporation"})
            self.env["ir.model.data"]._update_xmlids(
                [
                    {
                        "xml_id": "base.res_partner_2",
                        "record": demo_partner,
                        "noupdate": False,
                    }
                ]
            )
        self.start_tour("/odoo", "account_accountant_tour", login="admin")
