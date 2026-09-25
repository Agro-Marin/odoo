from odoo import api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    for warehouse in env["stock.warehouse"].with_context(active_test=False).search([]):
        warehouse._create_or_update_route()
