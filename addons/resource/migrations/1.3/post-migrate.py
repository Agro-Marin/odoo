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
            continue
        Model = env[model_name]
        if Model._abstract or Model._transient or not Model._auto:
            continue
        table = SQL.identifier(Model._table)

        active_field = Model._fields.get("active")
        hours_field = Model._fields.get("allocated_hours")
        if not (
            hours_field is not None
            and hours_field.store
            and hours_field.compute == "_compute_allocated_hours"
            and "reservation_ids" in Model._fields
            and active_field is not None
            and active_field.store
        ):
            continue

        cr.execute(SQL("SELECT id FROM %s WHERE active = FALSE", table))
        archived_ids = [row[0] for row in cr.fetchall()]
        records = Model.browse(archived_ids)
        for start in range(0, len(archived_ids), BATCH_SIZE):
            batch = records[start : start + BATCH_SIZE]
            env.add_to_compute(hours_field, batch)
            batch.flush_recordset(["allocated_hours"])
            cr.commit()
        if archived_ids:
            _logger.info(
                "resource 1.3: recomputed allocated_hours for %d"
                " archived %s records (re-run of the 1.2 repair,"
                " with the active_test=False bug removed).",
                len(archived_ids),
                model_name,
            )
