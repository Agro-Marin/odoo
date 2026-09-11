"""Rebuild stored scheduling projections after all consumer schemas are ready."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["appointment.booking.line"].with_context(active_test=False).search([])
    env.add_to_compute(lines._fields["capacity_used"], lines)
    lines.flush_recordset(["capacity_used"])
    records = env["calendar.event"].search([("appointment_type_id", "!=", False)])
    for offset in range(0, len(records), 500):
        records[offset : offset + 500]._sync_reservations()
