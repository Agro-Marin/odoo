import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.cloud_storage_s3.tools import s3

_logger = logging.getLogger(__name__)

LEGACY_KEY_PARAMS = (
    "cloud_storage_s3_access_key_id",
    "cloud_storage_s3_secret_access_key",
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _move_keys_to_vault(env)


def _move_keys_to_vault(env):
    icp = env["ir.config_parameter"].sudo()
    access_key_id, secret_access_key = (icp.get_param(k) for k in LEGACY_KEY_PARAMS)
    if access_key_id and secret_access_key:
        s3.store_keys(env, access_key_id, secret_access_key)
        _logger.info(
            "cloud_storage_s3: IAM keys moved from system parameters to the vault"
        )
    icp.search([("key", "in", LEGACY_KEY_PARAMS)]).unlink()
