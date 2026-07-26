from .models import model_multicompany


def _auto_install_enterprise_dependencies(env):
    module_list = ["accountant"]
    module_ids = env["ir.module.module"].search(
        [("name", "in", module_list), ("state", "=", "uninstalled")]
    )
    module_ids.sudo().button_install()
