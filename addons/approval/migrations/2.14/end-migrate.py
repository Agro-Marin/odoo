import logging

from odoo import SUPERUSER_ID, api
from odoo.db.schema import column_exists, table_exists
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def _verb_of(env, model_name, method):
    for verb_name, verb in env.registry.model_verbs.get(model_name, {}).items():
        if method in (*verb.methods, *verb.checkpoints) or method == verb_name:
            return verb_name
    return None


def migrate(cr, version):
    if not version or not table_exists(cr, "approval_gate"):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Binding = env["approval.binding"].with_context(active_test=False)
    # a database that skipped the version adding approval_gate.active never
    # had a gate archived, so every one of its gates reads as active
    active = (
        SQL("active") if column_exists(cr, "approval_gate", "active") else SQL("TRUE")
    )
    cr.execute(
        SQL(
            "SELECT model_name, operation, enforced, %s FROM approval_gate "
            "ORDER BY model_name, operation",
            active,
        )
    )
    for model_name, operation, enforced, active in cr.fetchall():
        verb = _verb_of(env, model_name, operation)
        binding = verb and Binding.search(
            [
                ("model_name", "=", model_name),
                ("verb", "=", verb),
                ("origin", "=", "module"),
            ],
            limit=1,
        )
        if not binding:
            _logger.log(
                logging.WARNING if active else logging.INFO,
                "Code gate %s.%s (%s) has no shipped obligation in this registry; "
                "its decision is not carried and its module's obligation ships in "
                "Request mode when it is installed.",
                model_name,
                operation,
                "enforcing" if enforced else "watching",
            )
            continue
        mode = "request" if enforced else "advise"
        if binding.mode != mode:
            binding.mode = mode
        cr.execute(
            SQL(
                """
                UPDATE approval_observation
                   SET binding_id = %s
                 WHERE binding_id IS NULL
                   AND model_name = %s
                   AND operation IN %s
                """,
                binding.id,
                model_name,
                (verb, operation),
            )
        )
        _logger.info(
            "Code gate %s.%s is the obligation %s on the verb %s, mode %s; "
            "%s watched calls now count on it.",
            model_name,
            operation,
            binding.id,
            verb,
            mode,
            cr.rowcount,
        )
    # the ORM keeps a removed model's table, and nothing reads this one any more
    cr.execute(SQL("DROP TABLE approval_gate CASCADE"))
    _logger.info("approval_gate dropped: the code gates are obligations now.")
