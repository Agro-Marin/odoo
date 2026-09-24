import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

# the methods the code gates held, and the verb each is a door of now
DOOR_VERBS = {
    ("account.move", "action_post"): "post",
    ("sale.order", "action_confirm"): "confirm",
    ("purchase.order", "action_confirm"): "confirm",
    ("maintenance.order", "action_confirm"): "confirm",
    ("rma.order", "action_confirm"): "confirm",
    ("stock.picking", "button_validate"): "validate",
    ("stock.inventory.adjustment", "_apply"): "apply",
    ("ai.tool.call", "action_apply"): "apply",
}


def _rename(cr, table, model_column, operation_column):
    renamed = 0
    for (model_name, method), verb in DOOR_VERBS.items():
        cr.execute(
            SQL(
                "UPDATE %s SET %s = %s WHERE %s = %s AND %s = %s",
                SQL.identifier(table),
                SQL.identifier(operation_column),
                verb,
                SQL.identifier(model_column),
                model_name,
                SQL.identifier(operation_column),
                method,
            )
        )
        if cr.rowcount:
            _logger.info(
                "%s: %s rows of %s.%s name the verb %s now.",
                table,
                cr.rowcount,
                model_name,
                method,
                verb,
            )
        renamed += cr.rowcount
    return renamed


def migrate(cr, version):
    if not version:
        return
    requests = _rename(cr, "approval_request", "res_model", "operation")
    observations = _rename(cr, "approval_observation", "model_name", "operation")
    converted = 0
    for (model_name, method), verb in DOOR_VERBS.items():
        cr.execute(
            SQL(
                """
                UPDATE approval_binding binding
                   SET verb = %s, method = NULL
                  FROM ir_model model
                 WHERE model.id = binding.model_id
                   AND model.model = %s
                   AND binding.method = %s
             RETURNING binding.id
                """,
                verb,
                model_name,
                method,
            )
        )
        for (binding_id,) in cr.fetchall():
            converted += 1
            _logger.info(
                "Approval binding %s on %s.%s binds the verb %s now.",
                binding_id,
                model_name,
                method,
                verb,
            )
    cr.execute(
        SQL("DELETE FROM ir_config_parameter WHERE key = %s", "approval.gate_enforced")
    )
    _logger.info(
        "Code gates become verb obligations: %s requests, %s observations renamed, "
        "%s method bindings moved onto their verb.",
        requests,
        observations,
        converted,
    )
