import logging

from odoo import api

_logger = logging.getLogger(__name__)

_RENAMED_FROM = "base_credential_manager"


def adopt_renamed_module(cr) -> int:
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = %s AND state != 'uninstalled'",
        (_RENAMED_FROM,),
    )
    if not cr.fetchone():
        return 0

    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'credential'
           AND name IN (SELECT name FROM ir_model_data WHERE module = %s)
        """,
        (_RENAMED_FROM,),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = 'credential' WHERE module = %s",
        (_RENAMED_FROM,),
    )
    adopted = cr.rowcount

    cr.execute(
        "UPDATE ir_module_module_dependency SET name = 'credential' WHERE name = %s",
        (_RENAMED_FROM,),
    )
    repointed = cr.rowcount

    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        (_RENAMED_FROM,),
    )

    _logger.info(
        "credential: adopted %s record(s) and %s dependency row(s) from the "
        "pre-rename %s module, which is now retired",
        adopted,
        repointed,
        _RENAMED_FROM,
    )
    return adopted


_ADOPTED_FROM_TRANSPORT = (
    "ir_cron_check_expiring_credentials",
    "field_credential_credential__date_expiry_warned",
)

_EXPIRY_CRON_NAME = "Credential Manager: Check Expiring Credentials"


def adopt_expiry_cron(cr) -> int:
    cr.execute(
        "SELECT 1 FROM ir_model_data WHERE module = 'api_transport' AND name = ANY(%s)",
        (list(_ADOPTED_FROM_TRANSPORT),),
    )
    if not cr.fetchone():
        return 0

    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'credential' AND name = ANY(%s)",
        (list(_ADOPTED_FROM_TRANSPORT),),
    )
    cr.execute(
        """
        UPDATE ir_model_data SET module = 'credential'
         WHERE module = 'api_transport' AND name = ANY(%s)
        """,
        (list(_ADOPTED_FROM_TRANSPORT),),
    )
    adopted = cr.rowcount

    cr.execute(
        """
        SELECT c.id, c.ir_actions_server_id
          FROM ir_cron c
          JOIN ir_model_data d
            ON d.res_id = c.id
           AND d.model = 'ir.cron'
           AND d.module = 'credential'
           AND d.name = 'ir_cron_check_expiring_credentials'
        """
    )
    for cron_id, action_id in cr.fetchall():
        cr.execute(
            """
            UPDATE ir_act_server
               SET name = jsonb_set(
                       COALESCE(name, '{}'::jsonb), '{en_US}', to_jsonb(%s::text)
                   )
             WHERE id = %s
            """,
            (_EXPIRY_CRON_NAME, action_id),
        )
        cr.execute(
            "UPDATE ir_cron SET cron_name = %s WHERE id = %s",
            (_EXPIRY_CRON_NAME, cron_id),
        )

    _logger.info(
        "credential: adopted %s expiry-cron row(s) from api_transport", adopted
    )
    return adopted


def pre_init_hook(env: api.Environment) -> None:
    adopt_renamed_module(env.cr)
    adopt_expiry_cron(env.cr)
