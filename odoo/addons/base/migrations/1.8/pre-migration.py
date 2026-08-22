import logging

_logger = logging.getLogger(__name__)

_OLD = "_for_xml_id"
_NEW = "_get_action_dict_by_xml_id"

_COLUMNS = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)


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


def migrate(cr, version):
    for table, column in _COLUMNS:
        _rewrite(cr, table, column)
