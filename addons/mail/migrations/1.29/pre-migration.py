import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = (
    ("_detect_is_bounce", "_is_bounce"),
    ("_detect_loop_sender_created_too_many", "_has_loop_sender_created_too_many"),
    ("_detect_loop_sender_replied_too_often", "_has_loop_sender_replied_too_often"),
    ("_detect_loop_sender", "_is_loop_sender"),
    ("_detect_loop_headers", "_has_loop_headers"),
    ("_detect_write_to_catchall", "_is_write_to_catchall"),
    ("_find_unfollow_block", "_resolve_unfollow_span"),
    ("_locate_unfollow_block", "_resolve_unfollow_block"),
    ("_document_backed", "_filtered_document_backed"),
    ("_filter_empty", "_filtered_empty"),
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
            "mail 1.29: %s.%s %s -> %s (%d row(s))",
            table,
            column,
            old,
            new,
            cr.rowcount,
        )
