"""Pre-migration: let base's data file own the categories it declares.

`get_or_create_category_id` inserts its `ir_model_data` row with
`noupdate = True`, and on a FRESH database it runs before any data file is read
-- the bootstrap pass populates `ir_module_module` from every manifest on the
addons path, and a manifest's `category` path creates a row per prefix. So the
27 categories `ir_module_category_data.xml` declares are, on essentially every
database, rows the bootstrap made first and the data file merely overwrote at
install time, when `mode` is "init" and `noupdate` is not consulted.

On an UPGRADE it is consulted, and the data file is skipped. That is what makes
the flag worth clearing here rather than leaving alone: this version's data file
adds `parent_id` to six records that had none, and an upgraded database would
take neither those parents nor any later correction to a name or a sequence.
Measured before this script existed -- `base.module_category_agriculture`, the
same shape one repo over, came through a `-u base` still at sequence NULL with
its declaration sitting unread in `agro_base`'s data.

THE FLAG IS CLEARED FOR NAMED ROWS ONLY, never for the model. Every other
`ir.module.category` row is auto-created from a manifest path and is declared by
no data file at all, so it appears in no module's `loaded_xmlids` -- and
`_process_end` reaps exactly the rows that are absent from `loaded_xmlids` and
not `noupdate`. Clearing the flag across the model would therefore delete every
auto-created category at the end of the load, null the `category_id` of every
module in one, and have `update_list` build them again on the next run. The flag
is what holds those rows in place; it is only wrong on the ones a data file
speaks for.
"""

import logging

_logger = logging.getLogger(__name__)

# The categories `odoo/addons/base/data/ir_module_category_data.xml` declares.
# A record added there wants its name here too, or the data file goes on being
# unable to correct it on an upgraded database.
DECLARED = (
    "module_category_accounting",
    "module_category_accounting_accounting",
    "module_category_accounting_localizations",
    "module_category_accounting_localizations_account_charts",
    "module_category_administration",
    "module_category_administration_administration",
    "module_category_customizations",
    "module_category_esg",
    "module_category_extra",
    "module_category_hidden",
    "module_category_human_resources",
    "module_category_human_resources_appraisals",
    "module_category_human_resources_referrals",
    "module_category_marketing",
    "module_category_payroll_localization",
    "module_category_productivity",
    "module_category_sales",
    "module_category_sales_sign",
    "module_category_services",
    "module_category_services_appointment",
    "module_category_services_field_service",
    "module_category_services_helpdesk",
    "module_category_shipping_connectors",
    "module_category_supply_chain",
    "module_category_supply_chain_iot",
    "module_category_theme",
    "module_category_website",
)


def migrate(cr, version):
    # `= ANY(%s)` with a list, never `IN %s`: psycopg 3 binds server-side, so
    # the placeholder reaches PostgreSQL as $1 and `IN $1` is a syntax error.
    cr.execute(
        """
        UPDATE ir_model_data SET noupdate = false
         WHERE module = 'base'
           AND model = 'ir.module.category'
           AND name = ANY(%s)
           AND COALESCE(noupdate, false)
        """,
        (list(DECLARED),),
    )
    if cr.rowcount:
        _logger.info(
            "%s declared module categor(y/ies) can now be corrected by base's "
            "data file; they were noupdate from the bootstrap pass",
            cr.rowcount,
        )
