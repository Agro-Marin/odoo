from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    identifiers = env["res.partner.identifier"].search([])
    if not identifiers:
        return
    identifiers.invalidate_recordset(["normalized_value"])
    identifiers.modified(["value"])
    identifiers._compute_normalized_value()
    identifiers.flush_recordset(["normalized_value"])
