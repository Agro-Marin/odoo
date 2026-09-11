from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["hr.expense"].search(
        [("review_state", "=", "submitted"), ("approval_request_id", "=", False)]
    )._backfill_approval_requests()
