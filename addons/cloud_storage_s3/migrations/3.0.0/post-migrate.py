import logging

from odoo import SUPERUSER_ID, api
from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.cloud_storage_s3.tools import drive_import, s3

_logger = logging.getLogger(__name__)

LEGACY_KEY_PARAMS = (
    "cloud_storage_s3_access_key_id",
    "cloud_storage_s3_secret_access_key",
)
DRIVE_PARAM_BUCKET = "cloud_drive_s3.bucket_name"
DRIVE_PARAM_REGION = "cloud_drive_s3.region"
DRIVE_CREDENTIAL_CODE = "drive_s3"
DRIVE_GROUP_TO_DOCUMENTS = {
    "group_drive_read": "document.group_documents_user",
    "group_drive_admin": "document.group_documents_manager",
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _move_keys_to_vault(env)
    _absorb_cloud_drive(env)


def _move_keys_to_vault(env):
    icp = env["ir.config_parameter"].sudo()
    access_key_id, secret_access_key = (icp.get_param(k) for k in LEGACY_KEY_PARAMS)
    if access_key_id and secret_access_key:
        s3.store_keys(env, access_key_id, secret_access_key)
        _logger.info(
            "cloud_storage_s3: IAM keys moved from system parameters to the vault"
        )
    icp.search([("key", "in", LEGACY_KEY_PARAMS)]).unlink()


def _drive_credential(env):
    return (
        env["credential.credential"]
        .sudo()
        .search(
            [("category_id.code", "=", DRIVE_CREDENTIAL_CODE), ("active", "=", True)],
            order="write_date desc, id desc",
            limit=1,
        )
    )


def _table_exists(cr, table):
    cr.execute(SQL("SELECT to_regclass(%s)", table))
    return cr.fetchone()[0] is not None


def _absorb_cloud_drive(env):
    cr = env.cr
    icp = env["ir.config_parameter"].sudo()
    bucket = icp.get_param(DRIVE_PARAM_BUCKET)
    region = icp.get_param(DRIVE_PARAM_REGION)
    if not (bucket and region and _table_exists(cr, "cloud_drive_access")):
        return
    if "document.document" not in env:
        _logger.warning(
            "cloud_storage_s3: a Cloud Drive bucket (%s) is configured but "
            "Documents is not installed; nothing imported",
            bucket,
        )
        return
    drive_keys = _drive_credential(env).get_credential_dict()
    if not s3.get_keys(env) and drive_keys:
        s3.store_keys(env, drive_keys["access_key_id"], drive_keys["secret_access_key"])
    if not icp.get_param(s3.PARAM_BUCKET):
        icp.set_param(s3.PARAM_BUCKET, bucket)
    if not icp.get_param(s3.PARAM_REGION):
        icp.set_param(s3.PARAM_REGION, region)
    client = s3.get_client(env)
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        raise UserError(
            env._(
                "The Amazon S3 keys stored for Cloud Storage cannot reach the "
                "Cloud Drive bucket '%(bucket)s' (%(error)s). Grant that IAM user "
                "s3:ListBucket, s3:GetObject and s3:DeleteObject on it, then run "
                "the upgrade again.",
                bucket=bucket,
                error=exc,
            )
        ) from exc

    cr.execute(
        "SELECT path, user_id, access_level FROM cloud_drive_access WHERE active"
    )
    grants = [
        {"path": path, "user_id": user_id, "access_level": level}
        for path, user_id, level in cr.fetchall()
    ]
    result = drive_import.import_bucket(
        env, client, bucket, region, root_name="Cloud", grants=grants
    )
    _logger.info(
        "cloud_storage_s3: Cloud Drive bucket %s imported into Documents: %s",
        bucket,
        result,
    )
    for grant in result["skipped_grants"]:
        _logger.warning("cloud_storage_s3: Cloud Drive grant not mapped: %s", grant)
    _move_drive_groups(env)
    icp.search([("key", "in", [DRIVE_PARAM_BUCKET, DRIVE_PARAM_REGION])]).unlink()


def _move_drive_groups(env):
    for drive_group, documents_group in DRIVE_GROUP_TO_DOCUMENTS.items():
        source = env.ref(f"cloud_drive_s3.{drive_group}", raise_if_not_found=False)
        if not source:
            continue
        env.ref(documents_group).sudo().user_ids |= source.user_ids
