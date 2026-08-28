import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_TABLE = "res_partner_age_range"

# res.partner.age.range, mixin.band and the partner demographic fields
# (gender, mobile, birthdate, age, age_range_id) moved into base. Their
# records already exist; only the module that owns them changes. This has to
# run here, in base's own pre-migration, and not in a migration of the modules
# being taken from: base is the first module loaded, so by the time marin or
# base_attribute_mixin gets a chance to hand anything over, base has already
# reflected the model and created a second ir_model_data row beside the one it
# should have adopted -- leaving the original to be reaped as an orphan, and
# ir.model.fields rows take their columns with them when they go.
_ADOPTED_NAMES = (
    "model_res_partner_age_range",
    "model_inherit__res_partner_age_range__mixin_band",
    "field_res_partner__age",
    "field_res_partner__age_range_id",
    "field_res_partner__birthdate",
    "field_res_partner__gender",
    "field_res_partner__mobile",
    # res.users _inherits res.partner, so every field added there is mirrored
    # onto it under its own xmlid. Left behind, these are ir.model.fields rows
    # owned by a module that no longer declares them -- and an ir.model.fields
    # row takes its column with it when it is reaped.
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
    # A Selection field owns one ir.model.fields.selection record per value,
    # each under its own xmlid. Reaped, the field keeps its column and loses
    # the values that make it readable.
    "selection__res_partner__gender__%",
)
_DONORS = ("marin", "base_attribute_mixin")

# The ACLs keep their permissions but not their spelling: base names an access
# rule after the group it grants, and marin named these admin/user.
_ADOPTED_RENAMES = {
    "access_res_partner_age_range_admin": (
        "access_res_partner_age_range_group_partner_manager"
    ),
    "access_res_partner_age_range_user": "access_res_partner_age_range_group_user",
}

# Databases that never reached marin 19.0.1.44 still spell the bounds age_from
# and age_to. That rename used to run in marin's own pre-migration, which was
# early enough while marin declared the model -- it no longer is. Reflecting
# base with the legacy columns still in place adds min_value and max_value
# empty beside them, and marin 19.0.1.44 then finds both spellings present,
# declines to rename, and leaves the seeded cohorts classifying nobody.
_RENAMES = (("age_from", "min_value"), ("age_to", "max_value"))

# The daily sweep this cron ran is gone: res.partner.age.range now re-applies
# the scale itself whenever a cohort is created, rebounded, archived or
# deleted, which is immediate where the sweep was up to a day late. Dropping
# the record belongs here rather than in marin's own upgrade because base is
# what removes _cron_update_age_range_id: a database that upgrades base alone
# would otherwise keep firing a cron at a method that no longer exists.
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
    # A base row of the same name can only exist if this migration already ran,
    # in which case the donor rows are gone and nothing below matches. Should
    # one somehow collide, base's row already points at the same record, so the
    # donor's is the one to drop -- (module, name) is unique.
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
    # ir_cron.ir_actions_server_id is ondelete=restrict, so the delegate row
    # goes first and the server action it points at second. ir_cron_trigger
    # cascades off the cron and needs no statement of its own.
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
