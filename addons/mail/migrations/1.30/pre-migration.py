import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = (
    ("_filter_mail_servers_fallback", "_filtered_mail_servers_fallback"),
    ("_filter_mail_mail_servers", "_filtered_mail_mail_servers"),
    ("_filter_ready_to_send", "_filtered_ready_to_send"),
    ("_filter_records_for_message_operation", "_get_accessible_documents"),
    ("_find_allowed_doc_ids", "_get_readable_message_ids"),
    ("_filter_records_followed_by_self", "_get_followed_res_ids"),
    ("_filter_has_field_access", "_filtered_has_field_access"),
    ("_filter_free_field_access", "_filtered_free_field_access"),
    ("_filter_superseded_attachments", "_filtered_unsuperseded_attachments"),
    ("_find_aliases", "_get_alias_emails"),
    ("_find_unknown_object_attribute", "_get_unknown_object_attribute_error"),
    ("_find_unknown_model_attribute", "_get_unknown_model_attribute_error"),
    ("_message_parse_bounce_find_part", "_message_parse_bounce_get_part"),
    ("_require_new_alias", "_is_new_alias_required"),
    ("_apply_alias_name_vals", "_update_alias_name_vals"),
    ("_set_voice_metadata", "_create_voice_metadata"),
    ("_set_value_from_template", "_update_value_from_template"),
    ("_set_mail_attributes", "_update_mail_attributes"),
    ("_set_new_message_separator", "_update_new_message_separator"),
    ("_group_by_model", "_grouped_by_model"),
    ("_resolve_partner_to", "_update_partner_to"),
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
            "mail 1.30: %s.%s %s -> %s (%d row(s))",
            table,
            column,
            old,
            new,
            cr.rowcount,
        )
