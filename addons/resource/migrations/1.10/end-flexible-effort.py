"""Repair derived Planning effort after correcting local-date/DST accounting."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    records = (
        env["resource.reservation"]
        .with_context(active_test=False)
        .search([("res_model", "=", "planning.slot"), ("resource_id", "!=", False)])
    )
    for offset in range(0, len(records), 500):
        records[offset : offset + 500].filtered(
            lambda record: record.resource_id._is_flexible()
        )._compute_allocated_hours()
