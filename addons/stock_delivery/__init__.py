from . import models
from . import wizard


def _auto_install_sale_app(env):
    if env["ir.module.module"]._get("website_sale").state != "uninstalled":
        return
    module_sale_management = env["ir.module.module"]._get("sale_management")
    if module_sale_management.state == "uninstalled":
        module_sale_management.button_install()
