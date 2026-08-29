import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_TABLE = "res_partner_age_range"

_ADOPTED_NAMES = (
    "model_res_partner_age_range",
    "model_inherit__res_partner_age_range__mixin_band",
    "field_res_partner__age",
    "field_res_partner__age_range_id",
    "field_res_partner__birthdate",
    "field_res_partner__gender",
    "field_res_partner__mobile",
    "field_res_users__age",
    "field_res_users__age_range_id",
    "field_res_users__birthdate",
    "field_res_users__gender",
    "field_res_users__mobile",
    "model_mixin_band",
)
_ADOPTED_PATTERNS = (
    "field_res_partner_age_range__%",
    "constraint_res_partner_age_range%",
    "field_mixin_band__%",
    "selection__res_partner__gender__%",
)
_DONORS = ("marin", "base_attribute_mixin")

_ADOPTED_RENAMES = {
    "access_res_partner_age_range_admin": (
        "access_res_partner_age_range_group_partner_manager"
    ),
    "access_res_partner_age_range_user": "access_res_partner_age_range_group_user",
}

_RENAMES = (("age_from", "min_value"), ("age_to", "max_value"))

_RETIRED_CRON = "ir_cron_partner_age_range"


def _rename_legacy_bounds(cr):
    if not schema.table_exists(cr, _TABLE):
        return []
    renamed = []
    for old_name, new_name in _RENAMES:
        if not schema.column_exists(cr, _TABLE, old_name):
            continue
        if schema.column_exists(cr, _TABLE, new_name):
            _logger.warning(
                "base 1.9: %s.%s and %s both exist, leaving them alone",
                _TABLE,
                old_name,
                new_name,
            )
            continue
        cr.execute(f'ALTER TABLE {_TABLE} RENAME COLUMN "{old_name}" TO "{new_name}"')
        cr.execute(
            "UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
            (new_name, "res.partner.age.range", old_name),
        )
        cr.execute(
            "UPDATE ir_model_data SET name = %s "
            "WHERE model = 'ir.model.fields' AND name = %s",
            (f"field_{_TABLE}__{new_name}", f"field_{_TABLE}__{old_name}"),
        )
        renamed.append(f"{old_name} -> {new_name}")
    return renamed


def _adopt(cr):
    cr.execute(
        """
        DELETE FROM ir_model_data donor
         WHERE donor.module = ANY(%s)
           AND (donor.name = ANY(%s) OR donor.name LIKE ANY(%s))
           AND EXISTS (
               SELECT 1 FROM ir_model_data held
                WHERE held.module = 'base' AND held.name = donor.name
           )
        """,
        (list(_DONORS), list(_ADOPTED_NAMES), list(_ADOPTED_PATTERNS)),
    )
    cr.execute(
        """
        UPDATE ir_model_data SET module = 'base'
         WHERE module = ANY(%s)
           AND (name = ANY(%s) OR name LIKE ANY(%s))
        """,
        (list(_DONORS), list(_ADOPTED_NAMES), list(_ADOPTED_PATTERNS)),
    )
    adopted = cr.rowcount

    for old_name, new_name in _ADOPTED_RENAMES.items():
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = ANY(%s)
               AND name = %s
               AND EXISTS (
                   SELECT 1 FROM ir_model_data held
                    WHERE held.module = 'base' AND held.name = %s
               )
            """,
            (list(_DONORS), old_name, new_name),
        )
        cr.execute(
            "UPDATE ir_model_data SET module = 'base', name = %s "
            "WHERE module = ANY(%s) AND name = %s",
            (new_name, list(_DONORS), old_name),
        )
        adopted += cr.rowcount
    return adopted


def _retire_cron(cr):
    cr.execute(
        """
        SELECT c.id, c.ir_actions_server_id
          FROM ir_cron c
          JOIN ir_model_data d ON d.model = 'ir.cron' AND d.res_id = c.id
         WHERE d.module = ANY(%s) AND d.name = %s
        """,
        (list(_DONORS), _RETIRED_CRON),
    )
    rows = cr.fetchall()
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = ANY(%s) AND name LIKE %s",
        (list(_DONORS), _RETIRED_CRON + "%"),
    )
    if not rows:
        return 0
    cr.execute("DELETE FROM ir_cron WHERE id = ANY(%s)", ([row[0] for row in rows],))
    cr.execute(
        "DELETE FROM ir_act_server WHERE id = ANY(%s)", ([row[1] for row in rows],)
    )
    return len(rows)


def migrate(cr, version):
    renamed = _rename_legacy_bounds(cr)
    adopted = _adopt(cr)
    retired = _retire_cron(cr)
    if renamed or adopted or retired:
        _logger.info(
            "base 1.9: adopted %s record(s) for res.partner.age.range, mixin.band "
            "and the partner demographic fields from %s; renamed %s legacy "
            "column(s) %s; retired %s age-range cron(s)",
            adopted,
            ", ".join(_DONORS),
            len(renamed),
            ", ".join(renamed) or "-",
            retired,
        )
