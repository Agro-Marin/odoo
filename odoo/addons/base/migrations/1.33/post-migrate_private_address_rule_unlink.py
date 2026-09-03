from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref("base.res_partner_private_address_rule", raise_if_not_found=False)
    if rule and not rule.perm_unlink:
        rule.perm_unlink = True
