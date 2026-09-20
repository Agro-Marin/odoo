import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

# The four recurrence mixins moved from `resource` to `base` (§2.2.2). They are
# abstract, so nothing stored moves -- but each still owns an `ir.model` row and
# an `ir.model.fields` row per field, and every one of those is attributed to
# `resource` in a database installed before the move.
#
# This has to run before `base` loads its models, which is why it is a
# pre-migrate in `base` and not a migration in `resource`. Left alone, `base`
# would create a second `ir_model_data` row under its own module for each of
# these -- (module, name) is unique, so the pair coexists -- and the `resource`
# row would then be an external id pointing at a model `resource` no longer
# declares. The module-update sweep drops such a row, and dropping the
# `ir_model_data` row of an `ir.model` deletes the model record with it, taking
# its fields and every consumer's inherited access along.
#
# Every kind the mixins own, and only those. Each pattern is anchored at the
# start of the name so that `model_inherit__account_move__mixin_recurrence_rule`
# is left alone: that row records *account*'s inheritance and belongs to
# `account`, while `model_inherit__mixin_recurrence_rrule__...` records one
# mixin inheriting another and moves with them.
#
# Measured rather than reasoned: an upgrade adopting only the model and field
# rows left `constraint_mixin_recurrence_rrule_month_day` behind under
# `resource` while `base` created its own, so one SQL constraint had two
# external ids naming two modules.
_MOVED_XMLID_PATTERNS = (
    "model_mixin_recurrence_%",
    "field_mixin_recurrence_%",
    "selection__mixin_recurrence_%",
    "constraint_mixin_recurrence_%",
    "model_inherit__mixin_recurrence_%",
)

# `resource` is not the only module these rows can still be attributed to.
# A database last upgraded before the `mixin_recurrence` module was dissolved
# (resource 1.11) holds them under that name, and `base` upgrades *before*
# `resource` -- so by the time resource 1.11 would re-point them to `resource`,
# `base` has already loaded the models and orphaned whatever it did not adopt.
# Adopting from both here is what makes that upgrade path arrive where a fresh
# install does; resource 1.11 then finds nothing of its own left to move and
# still retires the module row.
_FORMER_HOMES = ("resource", "mixin_recurrence")


def migrate(cr, version):
    if not version:
        return

    for pattern in _MOVED_XMLID_PATTERNS:
        # A database part-way through this migration already carries the `base`
        # row; the former home's is then the duplicate and not the survivor.
        cr.execute(
            SQL(
                """
                DELETE FROM ir_model_data AS stale
                      USING ir_model_data AS adopted
                      WHERE stale.module = ANY(%s)
                        AND stale.name LIKE %s
                        AND adopted.module = 'base'
                        AND adopted.name = stale.name
                """,
                list(_FORMER_HOMES),
                pattern,
            )
        )
        cr.execute(
            SQL(
                """
                UPDATE ir_model_data
                   SET module = 'base'
                 WHERE module = ANY(%s)
                   AND name LIKE %s
                """,
                list(_FORMER_HOMES),
                pattern,
            )
        )
        if cr.rowcount:
            _logger.info(
                "base 1.49: re-pointed %d %s external id(s) to base.",
                cr.rowcount,
                pattern.rstrip("%"),
            )
