from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    _edi_ubl_builder = "purchase.edi.xml.ubl_bis3"
