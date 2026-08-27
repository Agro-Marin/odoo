from odoo import fields, models


class Test_ConverterTest_ModelSub(models.Model):
    _name = "test_converter.test_model.sub"
    _description = "Test Converter Model Sub"

    name = fields.Char()
