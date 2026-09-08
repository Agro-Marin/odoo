import logging

_logger = logging.getLogger(__name__)

DISSOLVED = ("pos_product_stock", "pos_orderline_grouped_product")
STOCK_MODULE = "pos_product_stock"


def migrate(cr, version):
    if not version:
        return
    present = [name for name in DISSOLVED if _is_present(cr, name)]
    if not present:
        return

    if STOCK_MODULE in present:
        _drop_the_settings_view(cr)
        _adopt_the_fields(cr)
        _clear_a_warehouse_of_another_company(cr)
    for name in present:
        _retire_the_module(cr, name)


def _is_present(cr, name):
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = %s AND state != 'uninstalled'",
        (name,),
    )
    return bool(cr.fetchone())


def _drop_the_settings_view(cr):
    cr.execute(
        """
        DELETE FROM ir_ui_view
              WHERE id IN (SELECT res_id
                             FROM ir_model_data
                            WHERE module = %s
                              AND model = 'ir.ui.view')
        """,
        (STOCK_MODULE,),
    )
    _logger.info("point_of_sale 1.0.3: removed %s inheriting view(s).", cr.rowcount)
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.ui.view'",
        (STOCK_MODULE,),
    )


def _adopt_the_fields(cr):
    cr.execute(
        """
        DELETE FROM ir_model_data dissolved
              USING ir_model_data surviving
              WHERE dissolved.module = %s
                AND surviving.module = 'point_of_sale'
                AND surviving.model = dissolved.model
                AND surviving.name = dissolved.name
        """,
        (STOCK_MODULE,),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = 'point_of_sale' WHERE module = %s",
        (STOCK_MODULE,),
    )
    _logger.info(
        "point_of_sale 1.0.3: adopted %s row(s) from %s.", cr.rowcount, STOCK_MODULE
    )


def _clear_a_warehouse_of_another_company(cr):
    cr.execute(
        """
        SELECT config.id
          FROM pos_config config
          JOIN stock_warehouse warehouse ON warehouse.id = config.stock_warehouse_id
         WHERE warehouse.company_id IS DISTINCT FROM config.company_id
        """
    )
    foreign = [row[0] for row in cr.fetchall()]
    if not foreign:
        return
    cr.execute(
        "DELETE FROM pos_config_stock_location_rel WHERE config_id = ANY(%s)",
        (foreign,),
    )
    cr.execute(
        "UPDATE pos_config SET stock_warehouse_id = NULL WHERE id = ANY(%s)",
        (foreign,),
    )
    _logger.info(
        "point_of_sale 1.0.3: cleared a foreign-company warehouse on %s config(s).",
        len(foreign),
    )


def _retire_the_module(cr, name):
    cr.execute("DELETE FROM ir_module_module_dependency WHERE name = %s", (name,))
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        (name,),
    )
    _logger.info("point_of_sale 1.0.3: %s retired.", name)
