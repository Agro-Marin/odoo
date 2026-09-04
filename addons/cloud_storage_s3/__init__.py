from . import models


def uninstall_hook(env):
    icp = env["ir.config_parameter"]
    if icp.get_param("cloud_storage_provider") == "s3":
        env["res.config.settings"]._check_cloud_storage_uninstallable()
        icp.set_param("cloud_storage_provider", False)
    icp.search(
        [
            (
                "key",
                "in",
                [
                    "cloud_storage_s3_bucket_name",
                    "cloud_storage_s3_region",
                    "cloud_storage_s3_access_key_id",
                    "cloud_storage_s3_secret_access_key",
                ],
            )
        ]
    ).unlink()
