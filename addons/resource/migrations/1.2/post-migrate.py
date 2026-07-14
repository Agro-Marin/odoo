"""Repair resource.reservation data damaged by bugs fixed in resource 1.2.

Three defects could corrupt the reservation ledger before this version:

1. **Orphans** — ``resource.scheduling.mixin.unlink`` searched reservations
   without ``active_test=False``, so deleting an archived consumer (the
   common archive → cleanup flow) left its archived reservations behind
   forever, pointing at a nonexistent record.

2. **Mirror drift** — the reconcile helper was blind to archived
   reservations, so an archived row next to a live consumer (or an active
   duplicate created beside an archived twin) could leave ``active`` out of
   sync with the consumer's state.

3. **Stale aggregates** — the consumer's stored ``allocated_hours`` now
   depends on ``reservation_ids.active`` (archived consumers read 0);
   values stored before this version still hold the pre-archive sums.

All three repairs are idempotent; re-running this migration is a no-op.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute(
        "SELECT DISTINCT res_model FROM resource_reservation"
        " WHERE res_model IS NOT NULL"
    )
    model_names = [row[0] for row in cr.fetchall()]

    for model_name in model_names:
        if model_name not in env:
            # Consumer module uninstalled: keep the rows; origin_display
            # already falls back to the raw "model,id" reference.
            _logger.info(
                "resource 1.2: skipping reservations of unknown model %s.",
                model_name,
            )
            continue
        Model = env[model_name]
        if Model._abstract or Model._transient or not Model._auto:
            continue
        table = SQL.identifier(Model._table)

        # 1) Orphans: consumer record no longer exists.
        cr.execute(
            SQL(
                """
                DELETE FROM resource_reservation rr
                 WHERE rr.res_model = %s
                   AND NOT EXISTS (SELECT 1 FROM %s t WHERE t.id = rr.res_id)
                """,
                model_name,
                table,
            )
        )
        if cr.rowcount:
            _logger.info(
                "resource 1.2: deleted %d orphaned reservations of %s.",
                cr.rowcount,
                model_name,
            )

        # 2) Mirror repair: reservation.active must equal the consumer's
        # active state (models without an active column are always live).
        active_field = Model._fields.get("active")
        if active_field and active_field.store:
            cr.execute(
                SQL(
                    """
                    UPDATE resource_reservation rr
                       SET active = t.active
                      FROM %s t
                     WHERE rr.res_model = %s
                       AND rr.res_id = t.id
                       AND rr.active != t.active
                    """,
                    table,
                    model_name,
                )
            )
            if cr.rowcount:
                _logger.info(
                    "resource 1.2: re-mirrored active state of %d reservations of %s.",
                    cr.rowcount,
                    model_name,
                )

        # 3) Stale stored aggregates: every archived consumer's stored
        # ``allocated_hours`` predates the active-aware aggregate semantics.
        # Duck-typed on the mixin's compute so only scheduling consumers
        # (not unrelated models with a same-named field) are touched.
        hours_field = Model._fields.get("allocated_hours")
        if (
            hours_field is not None
            and hours_field.store
            and hours_field.compute == "_compute_allocated_hours"
            and "reservation_ids" in Model._fields
            and active_field is not None
            and active_field.store
        ):
            cr.execute(SQL("SELECT id FROM %s WHERE active = FALSE", table))
            archived_ids = [row[0] for row in cr.fetchall()]
            records = Model.with_context(active_test=False).browse(archived_ids)
            for start in range(0, len(archived_ids), BATCH_SIZE):
                batch = records[start : start + BATCH_SIZE]
                env.add_to_compute(hours_field, batch)
                batch.flush_recordset(["allocated_hours"])
                cr.commit()
            if archived_ids:
                _logger.info(
                    "resource 1.2: recomputed allocated_hours for %d"
                    " archived %s records.",
                    len(archived_ids),
                    model_name,
                )
