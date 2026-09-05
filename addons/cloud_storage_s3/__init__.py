from . import models, tools
from .tools import s3


def uninstall_hook(env):
    icp = env["ir.config_parameter"]
    if icp.get_param("cloud_storage_provider") == "s3":
        env["res.config.settings"]._check_cloud_storage_uninstallable()
        icp.set_param("cloud_storage_provider", False)
    icp.search([("key", "in", [s3.PARAM_BUCKET, s3.PARAM_REGION])]).unlink()
    env["credential.credential"].sudo().search(
        [("category_id.code", "=", "cloud_storage_s3"), ("active", "in", [True, False])]
    ).unlink()
    s3.clear_cache(env)
