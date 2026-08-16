from odoo import models


class BaseModuleUninstall(models.TransientModel):
    _inherit = "base.module.uninstall"

    def _get_models(self) -> models.Model:
        models = super()._get_models()
        return models.filtered("is_mail_thread")
