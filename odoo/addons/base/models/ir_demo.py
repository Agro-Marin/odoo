import odoo.modules.loading
from odoo import models
from odoo.libs.debug_log import DebugLog

from odoo.addons.base.models.ir_module import assert_log_admin_access

_debug = DebugLog(__name__)


class IrDemo(models.TransientModel):
    _name = "ir.demo"
    _description = "Demo"

    @assert_log_admin_access
    def install_demo(self) -> dict[str, str]:
        _debug.lifecycle("install_demo", uid=self.env.uid, db=self.env.cr.dbname)
        odoo.modules.loading.force_demo(self.env)
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/odoo",
        }
