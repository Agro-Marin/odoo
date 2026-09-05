import logging

_logger = logging.getLogger(__name__)

DISSOLVED = "uom_extended"

# The six seed records move to `uom` and keep their names; the four settings
# fields move to `product`, which is where the resolvers reading them now live.
UOM_RECORDS = (
    "product_uom_wat",
    "product_uom_kw",
    "product_uom_mw",
    "product_uom_hp",
    "product_uom_km_per_liter",
    "product_uom_miles_per_galon",
)

# data/uom_uom_data.xml shipped noupdate="1" in the dissolved module and still
# does here, so a corrected seed never reaches a database that already holds
# the row. Both corrections below were the dissolved module's own 19.0.1.1.0
# migration; a database that never reached that version can no longer run it.
WRONG_MPG_FACTOR = 2.3521458
RIGHT_MPG_FACTOR = 1.609344 / 3.785411784

RENAMES = (
    ("product_uom_wat", "w", "W"),
    ("product_uom_kw", "Kw", "kW"),
    ("product_uom_mw", "Mw", "MW"),
    ("product_uom_km_per_liter", "Km/l", "km/L"),
)


def migrate(cr, version):
    if not version:
        return
    if not _is_present(cr):
        return

    _drop_the_settings_view(cr)
    _adopt_the_units(cr)
    _hand_the_rest_to_product(cr)
    _correct_the_seeded_values(cr)
    _retire_the_module(cr)


def _is_present(cr):
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = %s AND state != 'uninstalled'",
        (DISSOLVED,),
    )
    return bool(cr.fetchone())


def _drop_the_settings_view(cr):
    """Delete the inheriting view, not just its xml id.

    The four settings are declared inside product's own
    `product_general_settings` block now. Left behind, this view would add a
    second copy of each one to the form -- and its xml id collides with
    product's, so it cannot simply be re-pointed like the rest.

    Consequence of doing it here rather than in product: a `-u uom` that does
    not also upgrade `product` takes the four settings off the form until
    `product` is upgraded. Deleting the row is still this module's job, because
    the blanket re-point below would otherwise strand the view with no xml id
    at all.
    """
    cr.execute(
        """
        DELETE FROM ir_ui_view
              WHERE id IN (SELECT res_id
                             FROM ir_model_data
                            WHERE module = %s
                              AND model = 'ir.ui.view')
        """,
        (DISSOLVED,),
    )
    _logger.info("uom 1.2: removed %s inheriting view(s).", cr.rowcount)
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.ui.view'",
        (DISSOLVED,),
    )


def _adopt_the_units(cr):
    """Re-point the seed rows BEFORE data/uom_data.xml loads.

    This is a pre-migration for that reason alone: the same six records are
    declared in uom's data file now, and an xml id still reading
    `uom_extended.product_uom_kw` would make `_load_records` create a second
    row rather than recognise the one already there.
    """
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'uom'
         WHERE module = %s
           AND model = 'uom.uom'
           AND name = ANY(%s)
        """,
        (DISSOLVED, list(UOM_RECORDS)),
    )
    _logger.info("uom 1.2: adopted %s unit(s) from %s.", cr.rowcount, DISSOLVED)


def _hand_the_rest_to_product(cr):
    cr.execute(
        """
        DELETE FROM ir_model_data dissolved
              USING ir_model_data surviving
              WHERE dissolved.module = %s
                AND surviving.module = 'product'
                AND surviving.model = dissolved.model
                AND surviving.name = dissolved.name
        """,
        (DISSOLVED,),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = 'product' WHERE module = %s",
        (DISSOLVED,),
    )
    _logger.info("uom 1.2: handed %s row(s) to product.", cr.rowcount)


def _correct_the_seeded_values(cr):
    # uom.uom.name is translate=True, so the value lives in a jsonb column and
    # the write has to target the en_US key rather than the column.
    for name, wrong, right in RENAMES:
        cr.execute(
            """
            UPDATE uom_uom
               SET name = jsonb_set(name, '{en_US}', to_jsonb(%s::text))
             WHERE id IN (SELECT res_id
                            FROM ir_model_data
                           WHERE module = 'uom'
                             AND model = 'uom.uom'
                             AND name = %s)
               AND name->>'en_US' = %s
            """,
            (right, name, wrong),
        )
        if cr.rowcount:
            _logger.info("uom 1.2: renamed %s from %s to %s.", name, wrong, right)

    cr.execute(
        """
        UPDATE uom_uom
           SET relative_factor = %s
         WHERE id IN (SELECT res_id
                        FROM ir_model_data
                       WHERE module = 'uom'
                         AND model = 'uom.uom'
                         AND name = 'product_uom_miles_per_galon')
           AND abs(relative_factor - %s) <= 1e-9
        """,
        (RIGHT_MPG_FACTOR, WRONG_MPG_FACTOR),
    )
    if cr.rowcount:
        _logger.info(
            "uom 1.2: MPG relative_factor corrected from %s to %s.",
            WRONG_MPG_FACTOR,
            RIGHT_MPG_FACTOR,
        )


def _retire_the_module(cr):
    """Flip the state, never run an uninstall.

    `button_immediate_uninstall` would delete every record the module ever
    created, which is precisely the data being adopted three functions above.
    The row itself stays so that a database keeps the record of what it once
    had; the loader ignores an uninstalled module with no manifest on disk.
    """
    cr.execute(
        "DELETE FROM ir_module_module_dependency WHERE name = %s",
        (DISSOLVED,),
    )
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        (DISSOLVED,),
    )
    _logger.info("uom 1.2: %s retired.", DISSOLVED)
