from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    api.Environment(cr, SUPERUSER_ID, {})["slide.channel"]._backfill_access_requests()
