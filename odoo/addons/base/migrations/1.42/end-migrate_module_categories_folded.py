"""End-migration: the module categories the vocabulary sweep left empty.

THE STAGE IS LOAD-BEARING, and `post` is the obvious wrong choice. A module's
categories are re-pointed by `ir.module.module.update_list`, which
`ModuleLoader.apply_module_requests` calls once for the whole registry --
AFTER base's own `post` migrations have run and before `run_end_migrations`.
A `post-` script therefore reads every category still holding the modules the
sweep moved, finds all 57 in use, and deletes nothing while logging that it
worked. Measured: "every folded category is still in use; nothing deleted" on a
database with all 57 present and empty by the end of the same run.

A manifest's ``category`` string is a PATH, and ``get_or_create_category_id``
turns each of its prefixes into an ``ir.module.category`` row keyed by an xml id
built from that path -- lowercased, spaces to underscores. So a manifest is not
choosing from a list; it is naming a row into existence. Two hundred and
nineteen manifests were naming rows nobody meant: ``Fleet`` beside
``Human Resources/Fleet``, ``Inventory/Inventory`` beside
``Supply Chain/Inventory``, ``Technical`` beside ``Hidden`` (whose row is
displayed "Technical"), and one manifest whose category was a summary sentence.
Re-pointing them at the canonical paths leaves the rows they used to name
behind, holding nothing.

Nothing reaps those rows. ``get_or_create_category_id`` inserts its
``ir_model_data`` row with ``noupdate = True`` and ``_process_end`` skips
``noupdate`` rows outright, so an emptied category survives every upgrade and
goes on offering itself as a facet in the Apps store search panel. This deletes
them, and only them.

THE PREDICATE IS NOT "HOLDS NO MODULE", and that is the whole reason for the
guard below. ``ir.module.category`` has a second, unrelated consumer:
``res.groups.privilege.category_id``, where a category is the heading of a block
on the access-rights page and is expected to hold no module at all. Nine such
rows exist across this workspace -- ``base`` declares ``master_data``,
``credential`` declares ``integration``, and ``agromarin`` declares seven more
from ``marin``, ``remote``, ``web_scraper``, ``product_asset`` and two demo
modules. Deleting a category with no modules would take every one of them and
silently drop the headings off the page. So a row goes only if it holds no
module, heads no privilege, and parents no other category.

``module_category_internet_of_things_(iot)`` is in the list for a different
reason: it was a declared record in ``base``'s own data and nothing ever used it
-- ``iot`` and its nine device modules said ``Administration/IoT`` and the
delivery bridges said ``Supply Chain/Internet of Things (IoT)``, so the declared
row held nothing while two auto-created rivals held eighteen modules between
them. The declaration is gone from the data file, which does NOT reap it: it too
carries ``noupdate = True``, from the bootstrap pass that created it before the
data file was ever read.
"""

import logging

_logger = logging.getLogger(__name__)

# Every xml id reachable from a manifest's `category` before the sweep and from
# none after it. `module_category_administration` is deliberately ABSENT: no
# manifest names it any more either, but it is a declared record and it still
# parents `module_category_administration_administration`, which carries the
# "to buy" module rows from `ir_module_module.xml`. The runtime guard would
# spare it anyway; leaving it out of the list keeps the list readable as intent.
FOLDED = (
    "module_category_account",
    "module_category_accounting_edi",
    "module_category_accounting_localization",
    "module_category_administration_iot",
    "module_category_ai",
    "module_category_approvals",
    "module_category_crm_in_marketing_automation",
    "module_category_extra_tools",
    "module_category_finance",
    "module_category_fleet",
    "module_category_geobi",
    "module_category_helpdesk",
    "module_category_human_resources_barcode",
    "module_category_installer",
    "module_category_internet_of_things",
    "module_category_internet_of_things_(iot)",
    "module_category_inventory",
    "module_category_inventory_approvals",
    "module_category_inventory_delivery",
    "module_category_inventory_inventory",
    "module_category_localization",
    "module_category_localization_mexico",
    "module_category_manufacturing",
    "module_category_manufacturing_maintenance",
    "module_category_manufacturing_manufacturing",
    "module_category_marketing_online_appointment",
    "module_category_marketing_social",
    "module_category_marketing_whatsapp",
    "module_category_point_of_sale",
    "module_category_point_of_sale_localizations",
    "module_category_point_of_sale_localizations_edi",
    "module_category_product",
    "module_category_productivity_productivity",
    "module_category_project",
    "module_category_project_management",
    "module_category_sales_commissions",
    "module_category_send_sms_to_customer_for_order_confirmation",
    "module_category_services_assets",
    "module_category_services_employee_hourly_cost",
    "module_category_services_expenses",
    "module_category_services_payroll",
    "module_category_services_payroll_account",
    "module_category_services_sales",
    "module_category_services_sales_subscriptions",
    "module_category_social",
    "module_category_supply_chain_internet_of_things_(iot)",
    "module_category_technical",
    "module_category_technical_settings",
    "module_category_theme_hidden",
    "module_category_tools",
    "module_category_uncategorized",
    "module_category_web",
    "module_category_website_sale",
    "module_category_website_sale_localizations",
    "module_category_website_sale_localizations_edi",
    "module_category_whatsapp",
)


def migrate(cr, version):
    # `= ANY(%s)` with a list, never `IN %s`: psycopg 3 binds server-side, so
    # the placeholder reaches PostgreSQL as $1 and `IN $1` is a syntax error.
    cr.execute(
        """
        SELECT d.id, d.name, c.id
          FROM ir_model_data d
          JOIN ir_module_category c ON c.id = d.res_id
         WHERE d.module = 'base'
           AND d.model = 'ir.module.category'
           AND d.name = ANY(%s)
        """,
        (list(FOLDED),),
    )
    found = cr.fetchall()
    if not found:
        return

    # ONE PASS IS NOT ENOUGH, and the shape is worth naming: several of these
    # categories parent each other. `Point of sale` holds nothing but
    # `Point of sale/Localizations`, which holds nothing but
    # `Point of sale/Localizations/EDI`. Testing the whole set against the tree
    # before deleting any of it counts a parent as in use on the strength of a
    # child that is about to go, so a single pass strands the parents -- measured
    # at 8 rows left behind with modules, children and privileges all zero.
    # Deleting deepest-first would do, but only because these chains are short;
    # repeating until a pass removes nothing is right whatever their depth.
    deleted: list[str] = []
    remaining = list(found)
    while True:
        kept = _still_in_use(cr, [category_id for _d, _n, category_id in remaining])
        doomed = [row for row in remaining if row[2] not in kept]
        if not doomed:
            break
        cr.execute(
            "DELETE FROM ir_model_data WHERE id = ANY(%s)",
            ([data_id for data_id, _n, _c in doomed],),
        )
        cr.execute(
            "DELETE FROM ir_module_category WHERE id = ANY(%s)",
            ([category_id for _d, _n, category_id in doomed],),
        )
        deleted += [name for _d, name, _c in doomed]
        remaining = [row for row in remaining if row[2] in kept]

    if not deleted:
        _logger.info("every folded category is still in use; nothing deleted")
        return
    _logger.info(
        "deleted %s emptied module categor(y/ies): %s",
        len(deleted),
        ", ".join(sorted(deleted)),
    )
    if remaining:
        _logger.info(
            "kept %s folded categor(y/ies) still holding something: %s",
            len(remaining),
            ", ".join(sorted(name for _d, name, _c in remaining)),
        )


def _still_in_use(cr, category_ids: list[int]) -> set[int]:
    """The subset of `category_ids` a database still has a reason to keep.

    A category that heads a block of access-rights privileges is EXPECTED to
    hold no module, so "holds no module" would delete exactly the rows that
    matter. All three tests, or the delete is wrong.
    """
    in_use: set[int] = set()
    for query in (
        "SELECT DISTINCT category_id FROM ir_module_module WHERE category_id = ANY(%s)",
        "SELECT DISTINCT parent_id FROM ir_module_category WHERE parent_id = ANY(%s)",
        "SELECT DISTINCT category_id FROM res_groups_privilege WHERE category_id = ANY(%s)",
    ):
        cr.execute(query, (category_ids,))
        in_use |= {row[0] for row in cr.fetchall()}
    return in_use
