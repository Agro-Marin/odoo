import logging

_logger = logging.getLogger(__name__)

RENAMES = (
    (
        "credential_credential",
        "credential.credential",
        "enable_rate_limiting",
        "decrypt_rate_limit_enabled",
    ),
    (
        "credential_credential",
        "credential.credential",
        "rate_limit_max_attempts",
        "decrypt_rate_limit_max",
    ),
    (
        "credential_category",
        "credential.category",
        "default_enable_rate_limiting",
        "default_decrypt_rate_limit_enabled",
    ),
    (
        "credential_category",
        "credential.category",
        "default_rate_limit_max_attempts",
        "default_decrypt_rate_limit_max",
    ),
)


def _columns(cr, table):
    cr.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        [table],
    )
    return {row[0] for row in cr.fetchall()}


def _move_column(cr, table, old, new):
    present = _columns(cr, table)
    if old not in present:
        return False
    if new in present:
        cr.execute(f'UPDATE "{table}" SET "{new}" = "{old}" WHERE "{old}" IS NOT NULL')
        cr.execute(f'ALTER TABLE "{table}" DROP COLUMN "{old}" CASCADE')
        _logger.info(
            "19.0.1.11.0: %s.%s carried into the existing %s, old column dropped",
            table,
            old,
            new,
        )
        return True
    cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
    _logger.info("19.0.1.11.0: %s.%s renamed to %s, values kept", table, old, new)
    return True


def migrate(cr, version):
    for table, model, old, new in RENAMES:
        _move_column(cr, table, old, new)

        cr.execute(
            """
            DELETE FROM ir_model_fields
             WHERE model = %s AND name = %s
               AND EXISTS (
                   SELECT 1 FROM ir_model_fields
                    WHERE model = %s AND name = %s
               )
            """,
            [model, old, model, new],
        )
        cr.execute(
            """
            UPDATE ir_model_fields
               SET name = %s
             WHERE model = %s AND name = %s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_fields
                    WHERE model = %s AND name = %s
               )
            """,
            [new, model, old, model, new],
        )

        cr.execute(
            """
            UPDATE ir_ui_view
               SET arch_db = regexp_replace(
                       arch_db::text, %s, %s, 'g'
                   )::jsonb
             WHERE arch_db::text ~ %s
            """,
            [rf"(?<![_a-z]){old}(?![_a-z])", new, rf"(?<![_a-z]){old}(?![_a-z])"],
        )
        if cr.rowcount:
            _logger.info(
                "19.0.1.11.0: rewrote %s stored view arch(es) for %s -> %s",
                cr.rowcount,
                old,
                new,
            )
