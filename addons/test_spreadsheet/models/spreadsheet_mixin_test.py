from odoo import models


class SpreadsheetTest(models.Model):
    """A very simple model only inheriting from mixin.spreadsheet to test
    its model functioning."""

    _description = "Dummy Spreadsheet"
    _name = "spreadsheet.test"
    _inherit = ["mixin.spreadsheet"]
