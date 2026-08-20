"""Recompute what the 1.4 ``allocated_percentage`` clamp invalidated.

``pre-migrate`` clamps out-of-range percentages with raw SQL, which cannot
refresh the stored ``allocated_hours`` derived from them — nor the
``allocated_hours`` aggregate the consumer records carry through
``mixin.resource.scheduling``.  Both are repaired here, from the ids
``pre-migrate`` parked in its scratch table.

The two halves use different tools on purpose:

* the reservations go through the ORM, because their ``allocated_hours``
  depends on the resource calendar and only ``_compute_allocated_hours``
  knows how to read it;
* the consumers are updated in SQL, because their models are **not in the
  registry yet**.  Odoo loads modules in dependency order, so while
  ``resource``'s own post-migrate runs, every module that consumes the mixin
  (``project`` and friends) is still unloaded — ``env['project.task']`` would
  raise.  The 1.2 script hits the same wall and simply logs "unknown model";
  the aggregate is a plain ``SUM`` over the ledger, so SQL can do it exactly.

No scratch table means nothing was out of range, which is the expected case.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCRATCH_TABLE = "_resource_mig_1_4_clamped"


def _refresh_consumer_aggregates(cr, res_ids_by_model):
    """Re-sum ``allocated_hours`` on the consumers of the clamped rows.

    Mirrors ``resource.scheduling.mixin._compute_allocated_hours``: the sum of
    the record's *active* reservations (``reservation_ids`` drops archived rows
    on read).
    """
    for model_name, res_ids in res_ids_by_model.items():
        cr.execute("SELECT model FROM ir_model WHERE model = %s", (model_name,))
        if not cr.fetchone():
            continue
        table = model_name.replace(".", "_")
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = 'allocated_hours'
            """,
            (table,),
        )
        if not cr.fetchone():
            continue

        cr.execute(
            SQL(
                """
                UPDATE %s t
                   SET allocated_hours = COALESCE(agg.total, 0)
                  FROM (SELECT res_id, SUM(allocated_hours) AS total
                          FROM resource_reservation
                         WHERE res_model = %s
                           AND active
                           AND res_id = ANY(%s)
                      GROUP BY res_id) agg
                 WHERE t.id = agg.res_id
                   AND t.allocated_hours IS DISTINCT FROM COALESCE(agg.total, 0)
                """,
                SQL.identifier(table),
                model_name,
                list(res_ids),
            )
        )
        if cr.rowcount:
            _logger.info(
                "resource 1.4: refreshed allocated_hours on %s %s record(s)",
                cr.rowcount,
                model_name,
            )


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
        "resource 1.4: recomputed allocated_hours on %s clamped reservation(s)",
        len(reservations),
    )

    res_ids_by_model = {}
    for reservation in reservations:
        if reservation.res_model and reservation.res_id:
            res_ids_by_model.setdefault(reservation.res_model, set()).add(
                reservation.res_id
            )
    if res_ids_by_model:
        _refresh_consumer_aggregates(cr, res_ids_by_model)
