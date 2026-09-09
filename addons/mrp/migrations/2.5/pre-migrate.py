from odoo.libs.sql import SQL
from odoo.tools.module_data import (
    absorb_readonly_forerunners,
    adopt_xmlids,
    remove_xmlid_records,
    retire_empty_module,
)

FROM_MODULE = "group_readonly"
MODULE = "mrp"
ADOPTED = (
    "group_mrp_readonly",
    "access_mrp_production_mrp_readonly",
    "access_mrp_production_group_mrp_readonly",
    "access_mrp_workorder_mrp_readonly",
    "access_mrp_bom_mrp_readonly",
    "access_mrp_bom_line_mrp_readonly",
    "access_mrp_bom_byproduct_mrp_readonly",
    "access_mrp_workcenter_mrp_readonly",
    "access_mrp_workcenter_capacity_mrp_readonly",
    "access_mrp_workcenter_tag_mrp_readonly",
    "access_mrp_workcenter_productivity_mrp_readonly",
    "access_mrp_workcenter_productivity_loss_mrp_readonly",
    "access_mrp_workcenter_productivity_loss_type_mrp_readonly",
    "access_mrp_routing_workcenter_mrp_readonly",
    "access_mrp_unbuild_mrp_readonly",
    "access_stock_move_mrp_readonly",
    "access_stock_picking_mrp_readonly",
    "access_stock_lot_mrp_readonly",
    "access_stock_scrap_mrp_readonly",
    "access_stock_scrap_reason_tag_mrp_readonly",
)
DROPPED = (
    "access_mrp_production_backorder_mrp_readonly",
    "access_mrp_production_backorder_line_mrp_readonly",
    "access_mrp_consumption_warning_mrp_readonly",
    "access_mrp_consumption_warning_line_mrp_readonly",
    "access_mrp_production_split_multi_mrp_readonly",
    "access_mrp_production_split_mrp_readonly",
    "access_mrp_production_split_line_mrp_readonly",
    "access_mrp_production_serials_mrp_readonly",
    "access_stock_move_line_mrp_readonly",
    "access_stock_picking_type_mrp_readonly",
    "access_stock_location_mrp_readonly",
    "access_stock_warehouse_mrp_readonly",
    "access_stock_quant_mrp_readonly",
    "access_product_product_mrp_readonly",
    "access_product_template_mrp_readonly",
    "access_product_category_mrp_readonly",
    "access_product_attribute_mrp_readonly",
    "access_product_attribute_value_mrp_readonly",
    "access_product_template_attribute_line_mrp_readonly",
    "access_product_template_attribute_value_mrp_readonly",
    "access_uom_uom_mrp_readonly",
    "access_res_partner_mrp_readonly",
    "access_res_company_mrp_readonly",
)


def migrate(cr, version):
    if not version:
        return
    absorb_readonly_forerunners(cr)
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    remove_xmlid_records(cr, FROM_MODULE, DROPPED)

    cr.execute(
        SQL(
            """
            DELETE FROM ir_act_server_group_rel r
             USING ir_model_data d
             WHERE d.module = %s AND d.name = 'group_mrp_readonly'
               AND d.model = 'res.groups' AND r.gid = d.res_id
            """,
            MODULE,
        )
    )
    retire_empty_module(cr, FROM_MODULE)
