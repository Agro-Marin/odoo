from typing import NamedTuple

from odoo import fields


class ProcurementException(Exception):
    """An exception raised by StockRule `run` containing all the faulty
    procurements.
    """

    def __init__(self, procurement_exceptions):
        """:param procurement_exceptions: list of (procurement, error message) tuples"""
        self.procurement_exceptions = procurement_exceptions


class Procurement(NamedTuple):
    """A request for a given quantity of a product to be available at a
    destination location, fulfilled by `StockRule.run` through stock moves,
    purchase orders, or manufacturing orders.
    """

    product_id: fields.Many2one
    product_qty: fields.Float
    product_uom_id: fields.Many2one
    location_id: fields.Many2one
    name: fields.Char
    origin: fields.Char
    company_id: fields.Many2one
    values: dict
