from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref("cloud_drive_s3.group_drive_upload", raise_if_not_found=False)
    if group:
        group.unlink()
