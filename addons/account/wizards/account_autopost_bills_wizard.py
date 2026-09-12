from odoo import fields, models

from ..tools import debug_log as dbg


class AccountAutopostBillsWizard(models.TransientModel):
    _name = "account.autopost.bills.wizard"
    _description = "Autopost Bills Wizard"

    partner_id = fields.Many2one("res.partner")
    partner_name = fields.Char(related="partner_id.name")
    nb_unmodified_bills = fields.Integer(
        "Number of bills previously unmodified from this partner"
    )

    @dbg.timed
    def action_automate_partner(self):
        dbg.lifecycle.debug("action_automate_partner on %s", dbg.rec(self))
        for wizard in self:
            wizard.partner_id.autopost_bills = "always"

    @dbg.timed
    def action_ask_later(self):
        dbg.lifecycle.debug("action_ask_later on %s", dbg.rec(self))
        for wizard in self:
            wizard.partner_id.autopost_bills = "ask"

    @dbg.timed
    def action_never_automate_partner(self):
        dbg.lifecycle.debug("action_never_automate_partner on %s", dbg.rec(self))
        for wizard in self:
            wizard.partner_id.autopost_bills = "never"
