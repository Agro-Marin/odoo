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
         WHERE table_name = 'automation_rule'
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
        cr.execute(f'ALTER TABLE automation_rule RENAME COLUMN "{old}" TO "{new}"')
        present.discard(old)
        present.add(new)
        renamed += 1

    if renamed:
        _logger.info(
            "automation 1.3: renamed %s webhook gate column(s) onto "
            "mixin.inbound.gate's names; values preserved",
            renamed,
        )

    if "auth_type" in present:
        cr.execute(
            "UPDATE automation_rule SET auth_type = 'none' WHERE auth_type IS NULL"
        )
        if cr.rowcount:
            _logger.info(
                "automation 1.3: defaulted auth_type to 'none' on %s rule(s) "
                "that had none set",
                cr.rowcount,
            )
