from odoo import fields, models


class Test_ConvertTest_Model(models.Model):
    _name = "test_convert.test_model"
    _description = "Test Convert Model"

    name = fields.Char(translate=True)
    usered_ids = fields.One2many("test_convert.usered", "test_id")
