from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    _edi_ubl_builder = "sale.edi.xml.ubl_bis3"
