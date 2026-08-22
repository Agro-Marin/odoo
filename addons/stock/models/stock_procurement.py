from typing import NamedTuple

from odoo import fields


class ProcurementException(Exception):
    def __init__(self, procurement_exceptions):
        self.procurement_exceptions = procurement_exceptions


class Procurement(NamedTuple):
    product_id: fields.Many2one
    product_qty: fields.Float
    product_uom_id: fields.Many2one
    location_id: fields.Many2one
    name: fields.Char
    origin: fields.Char
    company_id: fields.Many2one
    values: dict
