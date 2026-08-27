from odoo import api, fields, models


class Test_ConvertTest_Model(models.Model):
    _name = "test_convert.test_model"
    _description = "Test Convert Model"

    name = fields.Char(translate=True)
    usered_ids = fields.One2many("test_convert.usered", "test_id")

    @api.model
    def action_test_date(self, today_date):
        return True

    @api.model
    def action_test_time(self, cur_time):
        return True

    @api.model
    def action_test_timezone(self, timezone):
        return True
