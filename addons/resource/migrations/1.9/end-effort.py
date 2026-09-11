from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    records = (
        env["resource.reservation"]
        .with_context(active_test=False)
        .search(
            [
                ("allocated_hours", "=", 0),
                ("allocated_percentage", ">", 0),
            ]
        )
    )
    for offset in range(0, len(records), 500):
        records[offset : offset + 500]._compute_allocated_hours()
