from odoo import fields, models


class Test_ConverterMonetary(models.Model):
    _name = "test_converter.monetary"
    _description = "Test Converter Monetary"

    value = fields.Float()
