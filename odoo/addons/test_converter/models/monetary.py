from odoo import fields, models


class Test_ConverterMonetary(models.Model):
    _name = "test_converter.monetary"
    _description = "Test Converter Monetary"

    # value_to_html rounds through the destination currency, never the
    # field's own `digits` (see TestCurrencyExport) — no digits spec here.
    value = fields.Float()
