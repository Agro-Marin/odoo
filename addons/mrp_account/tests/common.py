from odoo.tests import Form, tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("-at_install", "post_install")
class TestBomPriceCommon(TestStockValuationCommon):
    @classmethod
    def _create_product(cls, name, price, quantity=100, category=None):
        vals = {
            "name": name,
            "is_storable": True,
            "standard_price": price,
            "qty_available": quantity,
        }
        if category:
            vals["categ_id"] = category.id
        return cls.Product.create(vals)

    @classmethod
    def _create_mo(cls, bom, quantity, confirm=True):
        mo = cls.env["mrp.production"].create(
            {
                "product_id": bom.product_id.id,
                "bom_id": bom.id,
                "product_qty": quantity,
            }
        )
        if confirm:
            mo.action_confirm()
        return mo

    @classmethod
    def _produce(cls, mo, quantity=0):
        mo_form = Form(mo)
        if not quantity:
            quantity = mo.product_qty - mo.qty_produced
        mo_form.qty_producing += quantity
        return mo_form.save()

    @classmethod
    def _use_production_accounting(cls):
        cls.account_production = cls.env["account.account"].create(
            {
                "name": "Production Account",
                "code": "100102",
                "account_type": "asset_current",
            }
        )
        production_locations = cls.env["stock.location"].search(
            [("usage", "=", "production"), ("company_id", "=", cls.company.id)]
        )
        production_locations.valuation_account_id = cls.account_production.id
        return cls.account_production

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("uom.group_uom")
        cls.env.user.group_ids += cls.env.ref("product.group_product_variant")
        cls.Product = cls.env["product.product"]
        cls.Bom = cls.env["mrp.bom"]
        cls.prod_location = cls.warehouse._get_production_location()

        cls.dining_table = cls._create_product(
            "Dining Table", 1000, quantity=0, category=cls.category_fifo_auto
        )
        cls.table_head = cls._create_product("Table Head", 300)
        cls.screw = cls._create_product("Screw", 10)
        cls.leg = cls._create_product("Leg", 25)
        cls.glass = cls._create_product(
            "Glass", 100, quantity=0, category=cls.category_avco_auto
        )

        cls.dozen = cls.env.ref("uom.product_uom_dozen")

        bom_form = Form(cls.Bom)
        bom_form.product_id = cls.dining_table
        bom_form.product_tmpl_id = cls.dining_table.product_tmpl_id
        bom_form.product_qty = 1.0
        bom_form.product_uom_id = cls.uom
        bom_form.type = "normal"
        with bom_form.bom_line_ids.new() as line:
            line.product_id = cls.table_head
            line.product_qty = 1
        with bom_form.bom_line_ids.new() as line:
            line.product_id = cls.screw
            line.product_qty = 5
        with bom_form.bom_line_ids.new() as line:
            line.product_id = cls.leg
            line.product_qty = 4
        with bom_form.bom_line_ids.new() as line:
            line.product_id = cls.glass
            line.product_qty = 1
        cls.bom_1 = bom_form.save()

        cls.plywood_sheet = cls._create_product("Plywood Sheet", 200)
        cls.bolt = cls._create_product("Bolt", 10)
        cls.colour = cls._create_product("Colour", 100)
        cls.corner_slide = cls._create_product("Corner Slide", 25)

        bom_form2 = Form(cls.Bom)
        bom_form2.product_id = cls.table_head
        bom_form2.product_tmpl_id = cls.table_head.product_tmpl_id
        bom_form2.product_qty = 1.0
        bom_form2.product_uom_id = cls.dozen
        bom_form2.type = "phantom"
        with bom_form2.bom_line_ids.new() as line:
            line.product_id = cls.plywood_sheet
            line.product_qty = 12
        with bom_form2.bom_line_ids.new() as line:
            line.product_id = cls.bolt
            line.product_qty = 60
        with bom_form2.bom_line_ids.new() as line:
            line.product_id = cls.colour
            line.product_qty = 12
        with bom_form2.bom_line_ids.new() as line:
            line.product_id = cls.corner_slide
            line.product_qty = 57
        cls.bom_2 = bom_form2.save()
        cls._use_production_accounting()


class TestBomPriceOperationCommon(TestBomPriceCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.write(
            {"group_ids": [(4, cls.env.ref("mrp.group_mrp_routings").id)]}
        )
        cls.account_expense_wo = cls.env["account.account"].create(
            {
                "code": "X2120",
                "name": "WO - Expenses",
                "account_type": "expense",
            }
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {
                "name": "Workcenter",
                "time_efficiency": 80,
                "oee_target": 100,
                "time_start": 15,
                "time_stop": 15,
                "costs_hour": 100,
                "expense_account_id": cls.account_expense_wo.id,
            }
        )
        cls.env["mrp.workcenter.capacity"].create(
            {
                "product_id": cls.dining_table.id,
                "workcenter_id": cls.workcenter.id,
                "time_start": 17,
                "time_stop": 16,
            }
        )

        cls.bom_1.write(
            {
                "operation_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Cutting",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 20,
                            "sequence": 1,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Drilling",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 25,
                            "sequence": 2,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Fitting",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 30,
                            "sequence": 3,
                        },
                    ),
                ],
            }
        )
        cls.bom_2.write(
            {
                "operation_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Cutting",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 20,
                            "sequence": 1,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Drilling",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 25,
                            "sequence": 2,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Fitting",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 30,
                            "sequence": 3,
                        },
                    ),
                ],
            }
        )

        cls.scrap_wood = cls._create_product("Scrap Wood", 30, quantity=0)

        cls.bom_1.write(
            {
                "byproduct_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.scrap_wood.id,
                            "product_uom_id": cls.uom.id,
                            "product_qty": 8,
                            "bom_id": cls.bom_1.id,
                            "cost_share": 1,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "product_id": cls.scrap_wood.id,
                            "product_uom_id": cls.dozen.id,
                            "product_qty": 1,
                            "bom_id": cls.bom_1.id,
                            "cost_share": 12,
                        },
                    ),
                ],
            }
        )
