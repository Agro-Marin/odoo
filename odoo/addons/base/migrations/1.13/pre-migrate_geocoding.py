import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_OLD_MODULE = "base_geolocalize"
_NEW_MODULE = "geocoding"

_MODEL_RENAMES = (
    ("base.geocoder", "geocoder"),
    ("base.geo_provider", "geocoder.provider"),
)
_TABLE_RENAMES = (("base_geo_provider", "geocoder_provider"),)

_XMLID_RENAMES = {
    "model_base_geocoder": "model_geocoder",
    "model_base_geo_provider": "model_geocoder_provider",
    "access_base_geo_provider": "access_geocoder_provider",
    "view_geo_provider_form": "view_geocoder_provider_form",
    "field_base_geocoder__display_name": "field_geocoder__display_name",
    "field_base_geocoder__id": "field_geocoder__id",
}
_XMLID_PREFIX_RENAMES = (("field_base_geo_provider__", "field_geocoder_provider__"),)

_SETTINGS_FIELD_RENAME = ("module_base_geolocalize", "module_geocoding")


def _module_row_id(cr):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (_OLD_MODULE,))
    row = cr.fetchone()
    return row[0] if row else None


def _rename_module(cr, module_id):
    cr.execute(
        "UPDATE ir_module_module SET name = %s WHERE id = %s",
        (_NEW_MODULE, module_id),
    )
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s",
        (_NEW_MODULE, _OLD_MODULE),
    )
    dependents = cr.rowcount
    cr.execute(
        "UPDATE ir_model_data SET name = %s WHERE module = 'base' AND name = %s",
        (f"module_{_NEW_MODULE}", f"module_{_OLD_MODULE}"),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s",
        (_NEW_MODULE, _OLD_MODULE),
    )
    owned = cr.rowcount
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE id = %s",
        (module_id,),
    )
    return dependents, owned


def _rename_models(cr):
    renamed = []
    for old_model, new_model in _MODEL_RENAMES:
        cr.execute(
            "UPDATE ir_model SET model = %s WHERE model = %s", (new_model, old_model)
        )
        if not cr.rowcount:
            continue
        cr.execute(
            "UPDATE ir_model_fields SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_model_data SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_ui_view SET model = %s WHERE model = %s", (new_model, old_model)
        )
        renamed.append(f"{old_model} -> {new_model}")
    return renamed


def _rename_tables(cr):
    renamed = []
    for old_table, new_table in _TABLE_RENAMES:
        if not schema.table_exists(cr, old_table):
            continue
        if schema.table_exists(cr, new_table):
            _logger.warning(
                "base 1.13: %s and %s both exist, leaving them alone",
                old_table,
                new_table,
            )
            continue
        cr.execute(f'ALTER TABLE "{old_table}" RENAME TO "{new_table}"')
        cr.execute(
            """
            SELECT conname FROM pg_constraint
             WHERE conrelid = %s::regclass AND conname LIKE %s
            """,
            (new_table, f"{old_table}%"),
        )
        for (conname,) in cr.fetchall():
            new_conname = f"{new_table}{conname[len(old_table) :]}"
            cr.execute(
                f'ALTER TABLE "{new_table}" RENAME CONSTRAINT "{conname}" '
                f'TO "{new_conname}"'
            )
            cr.execute(
                "UPDATE ir_model_constraint SET name = %s WHERE name = %s",
                (new_conname, conname),
            )
        renamed.append(f"{old_table} -> {new_table}")
    return renamed


def _rename_xmlids(cr):
    renamed = 0
    for old_name, new_name in _XMLID_RENAMES.items():
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s",
            (new_name, _NEW_MODULE, old_name),
        )
        renamed += cr.rowcount
    for old_prefix, new_prefix in _XMLID_PREFIX_RENAMES:
        cr.execute(
            """
            UPDATE ir_model_data
               SET name = %s || substring(name from %s)
             WHERE module = %s AND name LIKE %s
            """,
            (new_prefix, len(old_prefix) + 1, _NEW_MODULE, f"{old_prefix}%"),
        )
        renamed += cr.rowcount
    cr.execute(
        "UPDATE ir_model_access SET name = %s WHERE name = %s",
        ("access_geocoder_provider", "access_base_geo_provider"),
    )
    return renamed


def _rename_config_parameters(cr):
    cr.execute(
        """
        UPDATE ir_config_parameter
           SET key = %s || substring(key from %s)
         WHERE key LIKE %s
     RETURNING key
        """,
        (f"{_NEW_MODULE}.", len(_OLD_MODULE) + 2, f"{_OLD_MODULE}.%"),
    )
    return [row[0] for row in cr.fetchall()]


def _rename_settings_field(cr):
    old_field, new_field = _SETTINGS_FIELD_RENAME
    cr.execute(
        "UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
        (new_field, "res.config.settings", old_field),
    )
    if not cr.rowcount:
        return False
    cr.execute(
        "UPDATE ir_model_data SET name = %s WHERE module = 'web' AND name = %s",
        (
            f"field_res_config_settings__{new_field}",
            f"field_res_config_settings__{old_field}",
        ),
    )
    if schema.column_exists(cr, "res_config_settings", old_field) and not (
        schema.column_exists(cr, "res_config_settings", new_field)
    ):
        cr.execute(
            f'ALTER TABLE res_config_settings RENAME COLUMN "{old_field}" '
            f'TO "{new_field}"'
        )
    return True


def migrate(cr, version):
    if not version:
        return
    module_id = _module_row_id(cr)
    if module_id is None:
        return

    dependents, owned = _rename_module(cr, module_id)
    models = _rename_models(cr)
    tables = _rename_tables(cr)
    xmlids = _rename_xmlids(cr)
    parameters = _rename_config_parameters(cr)
    settings_field = _rename_settings_field(cr)

    _logger.info(
        "base 1.13: renamed module %s -> %s (%d dependency row(s), %d owned "
        "record(s)); models %s; tables %s; %d xmlid(s); config parameter(s) %s; "
        "res.config.settings toggle renamed: %s",
        _OLD_MODULE,
        _NEW_MODULE,
        dependents,
        owned,
        ", ".join(models) or "-",
        ", ".join(tables) or "-",
        xmlids,
        ", ".join(parameters) or "-",
        settings_field,
    )
