import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_TABLE = "res_partner_age_range"
_RECIPIENT = "partner"

_MOVED_NAMES = (
    "model_res_partner_age_range",
    "model_inherit__res_partner_age_range__mixin_band",
    "field_res_partner__age",
    "field_res_partner__age_range_id",
    "field_res_users__age",
    "field_res_users__age_range_id",
    "access_res_partner_age_range_group_user",
    "access_res_partner_age_range_group_partner_manager",
)
_MOVED_PATTERNS = (
    "field_res_partner_age_range__%",
    "constraint_res_partner_age_range%",
)

_LIVE_STATES = ("installed", "to upgrade", "to install")


def _recipient_is_live(cr):
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (_RECIPIENT,))
    row = cr.fetchone()
    return bool(row) and row[0] in _LIVE_STATES


def _hand_over(cr):
    # base no longer declares res.partner.age.range, so every xmlid still filed
    # under base is one ir.model.data._process_end would delete at the end of
    # this upgrade -- taking the ir.model row, and with it the table, along.
    # Filing them under partner before reflection runs is what turns a drop
    # into a hand-over: partner then finds the rows and reuses them.
    cr.execute(
        """
        DELETE FROM ir_model_data held
         WHERE held.module = %s
           AND (held.name = ANY(%s) OR held.name LIKE ANY(%s))
           AND EXISTS (
               SELECT 1 FROM ir_model_data donor
                WHERE donor.module = 'base' AND donor.name = held.name
           )
        """,
        (_RECIPIENT, list(_MOVED_NAMES), list(_MOVED_PATTERNS)),
    )
    cr.execute(
        """
        UPDATE ir_model_data SET module = %s
         WHERE module = 'base'
           AND (name = ANY(%s) OR name LIKE ANY(%s))
        """,
        (_RECIPIENT, list(_MOVED_NAMES), list(_MOVED_PATTERNS)),
    )
    return cr.rowcount


def _count_cohorts(cr):
    if not schema.table_exists(cr, _TABLE):
        return 0
    cr.execute(f"SELECT count(*) FROM {_TABLE}")
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return
    if not _recipient_is_live(cr):
        cohorts = _count_cohorts(cr)
        if cohorts:
            # ir.model._drop_table skips a model the registry no longer
            # knows, so the cohorts outlive the upgrade in an orphaned
            # table. What does not survive is res_partner.age_range_id:
            # base drops the column, and every classification with it.
            _logger.warning(
                "base 1.23: res.partner.age.range moved to the %s module, which "
                "is not installed here; base is about to drop "
                "res_partner.age_range_id, unclassifying every partner, and "
                "orphan the %s table and its %s cohort(s). Install %s before "
                "this upgrade to keep both",
                _RECIPIENT,
                _TABLE,
                cohorts,
                _RECIPIENT,
            )
        return
    moved = _hand_over(cr)
    if moved:
        _logger.info(
            "base 1.23: handed %s ir.model.data record(s) for "
            "res.partner.age.range and the partner age fields over to %s",
            moved,
            _RECIPIENT,
        )
