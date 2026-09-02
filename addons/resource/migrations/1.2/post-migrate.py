import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute(
        "SELECT DISTINCT res_model FROM resource_reservation"
        " WHERE res_model IS NOT NULL"
    )
    model_names = [row[0] for row in cr.fetchall()]

    for model_name in model_names:
        if model_name not in env:
            _logger.info(
                "resource 1.2: skipping reservations of unknown model %s.",
                model_name,
            )
            continue
        Model = env[model_name]
        if Model._abstract or Model._transient or not Model._auto:
            continue
        table = SQL.identifier(Model._table)

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
