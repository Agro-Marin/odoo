import logging
import re

import psycopg

from odoo import SUPERUSER_ID, api
from odoo.libs.logging import mute_logger

_logger = logging.getLogger(__name__)


def _is_valid_in_both_engines(cr, pattern):
    try:
        re.compile(pattern, re.IGNORECASE)
        with mute_logger("odoo.db.cursor"), cr.savepoint(flush=False):
            cr.execute("SELECT '' ~* %s", [pattern])
    except re.error, psycopg.errors.InvalidRegularExpression:
        return False
    return True


def migrate(cr, version):
    if not version:
        return
    # Label regexes used to be validated by Python alone while PostgreSQL runs
    # them, so a stored one PostgreSQL rejects breaks every matching query.
    cr.execute(
        """
        SELECT id, match_label_param
          FROM account_reconcile_model
         WHERE active
           AND match_label = 'match_regex'
           AND match_label_param IS NOT NULL
        """
    )
    invalid_ids = [
        model_id
        for model_id, pattern in cr.fetchall()
        if not _is_valid_in_both_engines(cr, pattern)
    ]
    if not invalid_ids:
        return
    _logger.warning(
        "Archiving reconciliation models %s: their label regex is not valid in "
        "both Python and PostgreSQL.",
        invalid_ids,
    )
    cr.execute(
        "UPDATE account_reconcile_model SET active = FALSE WHERE id = ANY(%s)",
        [invalid_ids],
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    models = env["account.reconcile.model"].browse(invalid_ids)
    models.invalidate_recordset(["active"])
    models._message_log_batch(
        bodies={
            model.id: env._(
                "Archived during the upgrade: the label regex %(regex)s is not "
                "valid in both Python and PostgreSQL, which run it. Fix it and "
                "unarchive the model.",
                regex=model.match_label_param,
            )
            for model in models
        }
    )
