"""Carry the ``webhook_*`` gate columns over to the shared gate's names.

ADR-0017 moves identity and admission onto ``inbound.gate.mixin``, which spells
these without the prefix. Renaming in ``pre-`` rather than ``post-`` for the
reason ``api_transport``'s 19.0.1.10.0 gives: the schema update would otherwise
create the new columns EMPTY beside the populated old ones, and every webhook
configured with a signature header, an allowlist or a credential would come back
up unauthenticated.

The ``webhook_*`` names survive as non-stored ``related`` aliases on the model,
so data files and code using them keep working for one release — that is what
lets a sibling repository (``agromarin/api_stock_scale`` seeds nine of them)
migrate on its own schedule rather than in the same commit.

Guarded per column and re-runnable: a rename only fires when the old column is
present and the new one is not.
"""

import logging

_logger = logging.getLogger(__name__)

_RENAMES = (
    ("webhook_auth_type", "auth_type"),
    ("webhook_credential_id", "credential_id"),
    ("webhook_signature_header", "signature_header"),
    ("webhook_signature_prefix", "signature_prefix"),
    ("webhook_timestamp_check", "timestamp_verification_enabled"),
    ("webhook_timestamp_header", "timestamp_header"),
    ("webhook_timestamp_max_age", "timestamp_max_age_seconds"),
    ("webhook_ip_allowlist", "ip_whitelist"),
    ("webhook_max_payload_size", "max_payload_size"),
    ("webhook_rate_limit", "rate_limit_enabled"),
    ("webhook_rate_limit_window", "rate_limit_window_seconds"),
)


def _columns(cr):
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'base_automation'
        """
    )
    return {row[0] for row in cr.fetchall()}


def migrate(cr, version):
    if not version:
        return

    present = _columns(cr)
    renamed = 0
    for old, new in _RENAMES:
        if old not in present or new in present:
            continue
        cr.execute(f'ALTER TABLE base_automation RENAME COLUMN "{old}" TO "{new}"')
        present.discard(old)
        present.add(new)
        renamed += 1

    if renamed:
        _logger.info(
            "base_automation 1.3: renamed %s webhook gate column(s) onto "
            "inbound.gate.mixin's names (ADR-0017); values preserved",
            renamed,
        )

    # `auth_type` is required on the gate. A rule predating the webhook fields,
    # or one whose column was never written, would fail the NOT NULL the ORM is
    # about to add — and "no authentication configured" is exactly what `none`
    # means, so it is the honest backfill rather than a placeholder.
    if "auth_type" in present:
        cr.execute(
            "UPDATE base_automation SET auth_type = 'none' WHERE auth_type IS NULL"
        )
        if cr.rowcount:
            _logger.info(
                "base_automation 1.3: defaulted auth_type to 'none' on %s rule(s) "
                "that had none set",
                cr.rowcount,
            )
