from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"
    _check_company_auto = True

    property_stock_customer = fields.Many2one(
        comodel_name="stock.location",
        string="Customer Location",
        company_dependent=True,
        check_company=True,
        domain="[('company_id', 'in', [False, allowed_company_ids[0]])]",
        help="The stock location used as destination when sending goods to this contact.",
    )
    property_stock_supplier = fields.Many2one(
        comodel_name="stock.location",
        string="Vendor Location",
        company_dependent=True,
        check_company=True,
        domain="[('company_id', 'in', [False, allowed_company_ids[0]])]",
        help="The stock location used as source when receiving goods from this contact.",
    )
    picking_warn_msg = fields.Text(string="Message for Stock Picking")

    def _set_stock_property_locations(self, location):
        """Point this partner's customer and supplier stock locations at ``location``.

        Both properties are ``company_dependent``: call through
        ``with_company(company)`` to target one company's value (batched across
        partners), and once per company to fan a single partner out over several.
        ``location`` may be an empty recordset to clear both properties.
        """
        self.write(
            {
                "property_stock_customer": location.id,
                "property_stock_supplier": location.id,
            },
        )

    def action_view_stock_serial(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock.action_stock_lot_form",
        )
        action["domain"] = [("partner_ids", "child_of", self.ids)]
        action["context"] = {"display_complete": True}
        return action
