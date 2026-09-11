from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model in ("hr.leave", "hr.leave.allocation"):
        env[model].search(
            [
                ("state", "in", ("confirm", "validate1")),
                ("approval_request_id", "=", False),
            ]
        )._backfill_approval_requests()
