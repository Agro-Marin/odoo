from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _sale_determine_order(self):
        mapping_from_project = self._get_so_mapping_from_project()
        mapping_from_expense = self._get_so_mapping_from_expense()
        mapping_from_project.update(mapping_from_expense)
        return mapping_from_project
