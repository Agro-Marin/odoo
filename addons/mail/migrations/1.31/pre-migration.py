import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = (
    ("_partner_find_from_emails_single", "_partner_get_or_create_from_emails_single"),
    ("_partner_find_from_emails_records", "_partner_get_or_create_from_emails_records"),
    ("_partner_find_from_emails_values", "_partner_get_or_create_from_emails_values"),
    (
        "_partner_find_from_emails_sort_key",
        "_partner_get_or_create_from_emails_sort_key",
    ),
    ("_partner_find_from_emails", "_partner_get_or_create_from_emails"),
    ("_mail_find_partner_from_emails", "_mail_get_or_create_partner_from_emails"),
    ("_routing_find_author", "_routing_get_author"),
    ("_routing_filter_local_aliases", "_routing_filtered_local_aliases"),
    ("_mail_find_referenced_message", "_mail_get_referenced_message"),
    ("_routing_filter_alias_recipients", "_routing_get_alias_recipients"),
    ("_mail_find_user_for_gateway", "_mail_get_user_for_gateway"),
    ("_track_filter_for_display", "_track_filtered_for_display"),
    ("_alias_filter_fields", "_alias_split_values"),
    (
        "_plan_filter_activity_templates_to_schedule",
        "_plan_filtered_activity_templates_to_schedule",
    ),
)

CODE_COLUMNS = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
)


def migrate(cr: Cursor, version: str | None) -> None:
    if not version:
        return
    for table, column in CODE_COLUMNS:
        if not _table_exists(cr, table):
            continue
        for old, new in RENAMES:
            _rewrite(cr, table, column, old, new)


def _table_exists(cr: Cursor, table: str) -> bool:
    cr.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return bool(cr.fetchone()[0])


def _rewrite(cr: Cursor, table: str, column: str, old: str, new: str) -> None:
    pattern = rf"\m{old}\M"
    cr.execute(
        f"UPDATE {table} SET {column} = regexp_replace({column}, %s, %s, 'g')"
        f" WHERE {column} ~ %s",
        (pattern, new, pattern),
    )
    if cr.rowcount:
        _logger.info(
            "mail 1.31: %s.%s %s -> %s (%d row(s))",
            table,
            column,
            old,
            new,
            cr.rowcount,
        )
