from odoo.addons.credential.hooks import adopt_expiry_cron


def migrate(cr, version):
    if not version:
        return
    adopt_expiry_cron(cr)
