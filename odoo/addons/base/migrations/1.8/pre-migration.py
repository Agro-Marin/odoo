import logging

_logger = logging.getLogger(__name__)

_OLD = "_for_xml_id"
_NEW = "_get_action_dict_by_xml_id"

_COLUMNS = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# Button renames this branch carries into view_server_action_form. The parent
# view and every inheriting child are both updated by the upgrade, but the
# parent's file loads first and revalidates its children against the arch still
# stored in the database -- so on an existing database the child is still
# xpath-ing the old name and the load dies with "cannot be located in parent
# view". A fresh install never sees it, because there the records are created in
# file order. Advance the stored arch before any view is loaded.
_VIEW_RENAMES = (("history_wizard_action", "action_open_code_history"),)


def _rewrite(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    if not cr.rowcount:
        return
    cr.execute(
        f'UPDATE "{table}"'
        f"    SET {column} = regexp_replace({column}, %s, %s, 'g')"
        f"  WHERE {column} ~ %s",
        (rf"\m{_OLD}\M", _NEW, rf"\m{_OLD}\M"),
    )
    if cr.rowcount:
        _logger.info(
            "%s.%s: rewrote %s -> %s in %s row(s)",
            table,
            column,
            _OLD,
            _NEW,
            cr.rowcount,
        )


def _rewrite_view_arch(cr, old, new):
    cr.execute(
        "UPDATE ir_ui_view"
        "    SET arch_db = regexp_replace(arch_db::text, %s, %s, 'g')::jsonb"
        "  WHERE arch_db::text ~ %s",
        (rf"\m{old}\M", new, rf"\m{old}\M"),
    )
    if cr.rowcount:
        _logger.info(
            "ir_ui_view.arch_db: rewrote %s -> %s in %s row(s)",
            old,
            new,
            cr.rowcount,
        )


def migrate(cr, version):
    for table, column in _COLUMNS:
        _rewrite(cr, table, column)
    for old, new in _VIEW_RENAMES:
        _rewrite_view_arch(cr, old, new)
