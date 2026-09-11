from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    records = env["calendar.event"].search([])
    for offset in range(0, len(records), 500):
        records[offset : offset + 500]._sync_reservations()
