import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    order_mixin = type(env["mixin.order.stock"])
    for model_name in env.registry:
        model = env[model_name]
        if model._abstract or model._transient:
            continue
        if not isinstance(model, order_mixin):
            continue
        field = model._fields.get("transfer_state")
        if field is None or not (field.store and field.compute):
            continue
        records = model.search([])
        if not records:
            continue
        for start in range(0, len(records), BATCH_SIZE):
            batch = records[start : start + BATCH_SIZE]
            env.add_to_compute(field, batch)
            batch.flush_recordset([field.name])
            cr.commit()
        _logger.info(
            "19.0.1.1.0: recomputing transfer_state on %s %s record(s)",
            len(records),
            model_name,
        )
    env.flush_all()
