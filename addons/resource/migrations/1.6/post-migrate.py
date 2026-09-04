import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCRATCH_TABLE = "_resource_mig_1_6_null_percentage"


def migrate(cr, version):
    if not version:
        return

    cr.execute(SQL("SELECT to_regclass(%s)", SCRATCH_TABLE))
    if not cr.fetchone()[0]:
        return

    cr.execute(SQL("SELECT id FROM %s", SQL.identifier(SCRATCH_TABLE)))
    reservation_ids = [row[0] for row in cr.fetchall()]
    cr.execute(SQL("DROP TABLE %s", SQL.identifier(SCRATCH_TABLE)))
    if not reservation_ids:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    reservations = (
        env["resource.reservation"]
        .with_context(active_test=False)
        .browse(reservation_ids)
        .exists()
    )
    if not reservations:
        return
    env.add_to_compute(reservations._fields["allocated_hours"], reservations)
    reservations.flush_recordset(["allocated_hours"])
    _logger.info(
        "resource 1.6: recomputed allocated_hours on %s repaired reservation(s)",
        len(reservations),
    )
