import json
import logging

_logger = logging.getLogger(__name__)

_MESSAGES = {
    "credential_category_api_key": "API Key credentials require a secret value.",
    "credential_category_bearer_token": "Bearer Token credentials require a token value.",
    "credential_category_basic_auth": "Basic Authentication requires username and password.",
    "credential_category_oauth2": (
        "OAuth 2.0 credentials require an access token, a refresh token or a "
        "client secret."
    ),
    "credential_category_aws_iam": (
        "AWS IAM credentials require Access Key ID and Secret Access Key."
    ),
}


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
            SELECT d.name, d.res_id
              FROM ir_model_data d
             WHERE d.module = 'credential'
               AND d.model = 'credential.category'
               AND d.name = ANY(%s)
        """,
        [list(_MESSAGES)],
    )
    filled = 0
    for name, res_id in cr.fetchall():
        cr.execute(
            """
                UPDATE credential_category
                   SET requirement_message = %s::jsonb
                 WHERE id = %s
                   AND requirement_message IS NULL
            """,
            [json.dumps({"en_US": _MESSAGES[name]}), res_id],
        )
        filled += cr.rowcount

    _logger.info(
        "credential.category: %s of %s requirement message(s) backfilled",
        filled,
        len(_MESSAGES),
    )
