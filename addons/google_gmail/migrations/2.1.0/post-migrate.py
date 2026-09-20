from odoo import SUPERUSER_ID, api

KEY = "google_gmail_client_secret"


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    parameters = env["ir.config_parameter"].sudo()
    secret = parameters.get_param(KEY)
    if secret:
        env["credential.credential"]._set_system_secret(KEY, secret)
    parameters.search([("key", "=", KEY)]).unlink()
