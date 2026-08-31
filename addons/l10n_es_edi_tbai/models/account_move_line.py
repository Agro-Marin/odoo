from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _l10n_es_tbai_is_ignored(self):
        self.check_singleton()

        return 'ignore' in self.tax_ids.mapped('l10n_es_type')
