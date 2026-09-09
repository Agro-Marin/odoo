import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = (
    ("fetch_mail", "action_poll_mailbox"),
    ("_fetch_mails", "_poll_due_mailboxes"),
    ("_fetch_mail", "_poll_mailboxes"),
    ("_fetch_twilio_ice_servers", "_get_twilio_ice_servers"),
    ("_verify_vapid_public_key", "_is_vapid_public_key_current"),
    ("_delete_and_notify", "_remove_and_notify"),
    ("_delete_inactive_rtc_sessions", "_remove_inactive_rtc_sessions"),
    ("_inactive_rtc_session_domain", "_get_domain_inactive_rtc_sessions"),
    ("_pending_email_notifications_domain", "_get_domain_pending_email_notifications"),
    ("_detect_loop_sender_domain", "_get_domain_loop_sender"),
    ("_compute_message_unread", "_compute_message_unread_counter"),
    ("_compute_message_needaction", "_compute_message_needaction_info"),
    ("_compute_message_has_error", "_compute_message_has_error_info"),
    ("_compute_outgoing_mail_server_id", "_compute_outgoing_mail_server_info"),
    ("_compute_error", "_compute_errors_and_warnings"),
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
            "mail 1.26: %s.%s %s -> %s (%d row(s))",
            table,
            column,
            old,
            new,
            cr.rowcount,
        )
