# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _
from odoo.exceptions import UserError


class StockPickingToBatch(models.TransientModel):
    _name = "stock.picking.to.batch"
    _description = "Batch Transfer Lines"


    batch_id = fields.Many2one(
        comodel_name="stock.picking.batch",
        string="Batch Transfer",
        domain=[("is_wave", "=", False), ("state", "in", ("draft", "in_progress"))],
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
    )
    mode = fields.Selection(
        [
            ("existing", "an existing batch transfer"),
            ("new", "a new batch transfer")
        ],
        default="new",
    )
    description = fields.Char("Description")
    is_create_draft = fields.Boolean(
        string="Draft",
        help="When checked, create the batch in draft status",
    )


    def attach_pickings(self):
        self.ensure_one()
        pickings = self.env["stock.picking"].browse(self.env.context.get("active_ids"))
        if self.mode == "new":
            company = pickings.company_id
            if len(company) > 1:
                raise UserError(_("The selected pickings should belong to an unique company."))

            batch = self.env["stock.picking.batch"].create({
                "company_id": company.id,
                "picking_type_id": pickings[0].picking_type_id.id,
                "user_id": self.user_id.id,
                "description": self.description,
            })
        else:
            batch = self.batch_id

        pickings.write({"batch_id": batch.id})
        # you have to set some pickings to batch before confirm it.
        if self.mode == "new" and not self.is_create_draft:
            batch.action_confirm()
        return {
            "name": _("Batch Transfer"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.batch",
            "view_mode": "form",
            "res_id": batch.id,
        }
