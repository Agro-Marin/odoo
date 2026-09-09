from odoo import models


class BaseModuleUninstall(models.TransientModel):
    _inherit = "base.module.uninstall"

    def _get_modules_to_display(self, modules):
        return super()._get_modules_to_display(modules) | modules.filtered("imported")
