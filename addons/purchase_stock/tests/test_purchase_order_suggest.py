from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.tests import freeze_time, tagged
from odoo.tests.common import HttpCase

from odoo.addons.purchase_stock.tests.common import PurchaseTestCommon


@freeze_time("2021-01-14 09:12:15")
@tagged("post_install", "-at_install")
class TestPurchaseOrderSuggest(PurchaseTestCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_1 = cls.env["product.product"].create(
            {
                "name": "Other Product",
                "standard_price": 115,
                "is_storable": True,
            }
        )
        cls.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": cls.vendor.id,
                    "price": 100,
                    "product_id": cls.product_1.id,
                }
            ]
        )
        cls.other_warehouse = cls.env["stock.warehouse"].create(
            {
                "name": "Other Warehouse",
                "code": "TWH2",
                "company_id": cls.env.company.id,
            }
        )

    def assertEstimatedPrice(
        self,
        po,
        price,
        based_on="30_days",
        days=30,
        factor=100,
        warehouse=False,
        domain=None,
    ):
        if domain is None:
            domain = []
        base_warehouse = self.picking_type_out.default_location_src_id.warehouse_id
        warehouse_id = (warehouse or base_warehouse).id
        suggest_context = {
            "order_id": po.id,
            "partner_id": po.partner_id.id,
            "warehouse_id": warehouse_id,
            "suggest_based_on": based_on,
            "suggest_days": days,
            "suggest_percent": factor,
        }
        products = (
            self.env["product.product"].with_context(suggest_context).search(domain)
        )
        products.invalidate_recordset(["suggest_estimated_price", "suggested_qty"])
        self.assertEqual(sum(products.mapped("suggest_estimated_price")), price)

    def actionAddAll(
        self, po, based_on="30_days", days=30, factor=100, warehouse=False
    ):
        base_warehouse = self.picking_type_out.default_location_src_id.warehouse_id
        warehouse_id = (warehouse or base_warehouse).id
        suggest_context = {
            "warehouse_id": warehouse_id,
            "suggest_based_on": based_on,
            "suggest_percent": factor,
            "suggest_days": days,
        }
        po.with_context(suggest_context).action_purchase_order_suggest()

    def _create_and_process_delivery_at_date(
        self, products_and_quantities, date=False, warehouse=False, to_validate=True
    ):
        date = date or datetime.now()
        delivery_type = warehouse.out_type_id if warehouse else self.picking_type_out
        with freeze_time(date):
            delivery = self.env["stock.picking"].create(
                {
                    "picking_type_id": self.picking_type_out.id,
                    "location_id": delivery_type.default_location_src_id.id,
                    "location_dest_id": delivery_type.default_location_dest_id.id,
                    "move_ids": [
                        Command.create(
                            {
                                "location_id": delivery_type.default_location_src_id.id,
                                "location_dest_id": delivery_type.default_location_dest_id.id,
                                "product_id": product.id,
                                "product_uom_id": self.uom.id,
                                "product_uom_qty": qty,
                            }
                        )
                        for (product, qty) in products_and_quantities
                    ],
                }
            )
            delivery.action_confirm()
            if to_validate:
                delivery.action_assign()
                delivery.button_validate()
            return delivery

    def test_purchase_order_suggest_quantities(self):
        today = fields.Datetime.now()
        product_2, product_3, product_4, product_5, product_6 = self.env[
            "product.product"
        ].create(
            [
                {
                    "name": f"Product {i + 1}",
                    "standard_price": price,
                    "is_storable": True,
                }
                for (i, price) in enumerate([25, 50, 100, 50, 25])
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_1, self.stock_location, 42
        )
        self.env["stock.quant"]._update_available_quantity(
            product_2, self.stock_location, 15
        )
        self.env["stock.quant"]._update_available_quantity(
            product_3, self.stock_location, 20
        )

        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "price": 20,
                    "product_id": product_2.id,
                },
                {
                    "partner_id": self.vendor.id,
                    "price": 50,
                    "product_id": product_3.id,
                },
            ]
        )

        self._create_and_process_delivery_at_date(
            [(self.product_1, 12)], today - relativedelta(years=1)
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 5), (product_2, 5)],
            today - relativedelta(months=10, days=3),
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 5), (product_3, 10)],
            today - relativedelta(months=2, days=5),
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 10), (product_3, 10)], today - relativedelta(days=30)
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 10), (product_2, 5)], today - relativedelta(days=15)
        )
        self._create_and_process_delivery_at_date(
            [(product_2, 5)], today - relativedelta(days=3)
        )

        self.assertEqual(self.product_1.monthly_demand, 20)
        self.assertEqual(product_2.monthly_demand, 10)
        self.assertEqual(product_3.monthly_demand, 10)
        context = {"suggest_based_on": "one_week"}
        self.assertEqual(self.product_1.with_context(context).monthly_demand, 0)
        self.assertAlmostEqual(
            product_2.with_context(context).monthly_demand,
            5 * (365.25 / 12) / 7,
            places=6,
        )
        self.assertEqual(product_3.with_context(context).monthly_demand, 0)
        context = {"suggest_based_on": "three_months"}
        self.assertAlmostEqual(
            self.product_1.with_context(context).monthly_demand, 25 / 3, places=6
        )
        self.assertAlmostEqual(
            product_2.with_context(context).monthly_demand, 10 / 3, places=6
        )
        self.assertAlmostEqual(
            product_3.with_context(context).monthly_demand, 20 / 3, places=6
        )
        context = {"suggest_based_on": "one_year"}
        self.assertAlmostEqual(
            self.product_1.with_context(context).monthly_demand, 42 / 12, places=6
        )
        self.assertAlmostEqual(
            product_2.with_context(context).monthly_demand, 15 / 12, places=6
        )
        self.assertAlmostEqual(
            product_3.with_context(context).monthly_demand, 20 / 12, places=6
        )
        context = {"suggest_based_on": "last_year"}
        self.assertEqual(self.product_1.with_context(context).monthly_demand, 12)
        self.assertEqual(product_2.with_context(context).monthly_demand, 0)
        self.assertEqual(product_3.with_context(context).monthly_demand, 0)
        context = {"suggest_based_on": "last_year_m_plus_1"}
        self.assertEqual(self.product_1.with_context(context).monthly_demand, 0)
        self.assertEqual(product_2.with_context(context).monthly_demand, 0)
        self.assertEqual(product_3.with_context(context).monthly_demand, 0)
        context = {"suggest_based_on": "last_year_m_plus_2"}
        self.assertEqual(self.product_1.with_context(context).monthly_demand, 5)
        self.assertEqual(product_2.with_context(context).monthly_demand, 5)
        self.assertEqual(product_3.with_context(context).monthly_demand, 0)

        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        self.assertEstimatedPrice(po, 2700)
        self.assertEstimatedPrice(po, 1350, days=15)
        self.assertEstimatedPrice(po, 3410, factor=125)
        self.assertEstimatedPrice(po, 1330, based_on="three_months")
        self.assertEstimatedPrice(po, 3700, based_on="three_months", days=90)
        self.assertEstimatedPrice(po, 540, based_on="one_year")
        self.assertEstimatedPrice(po, 5500, based_on="one_year", days=365)

        self.actionAddAll(po, based_on="30_days", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 20},
                {"product_id": product_2.id, "product_qty": 10},
                {"product_id": product_3.id, "product_qty": 10},
            ],
        )
        self.actionAddAll(po, based_on="three_months", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 9},
                {"product_id": product_2.id, "product_qty": 4},
                {"product_id": product_3.id, "product_qty": 7},
            ],
        )
        self.actionAddAll(po, based_on="three_months", days=90, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 25},
                {"product_id": product_2.id, "product_qty": 10},
                {"product_id": product_3.id, "product_qty": 20},
            ],
        )

        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "price": 90,
                    "product_id": product_4.id,
                },
                {
                    "partner_id": self.vendor.id,
                    "price": 45,
                    "product_id": product_5.id,
                },
                {
                    "partner_id": self.vendor.id,
                    "price": 24,
                    "product_id": product_6.id,
                },
            ]
        )

        self.env["stock.quant"]._update_available_quantity(
            product_4, self.stock_location, 1
        )
        self.env["stock.quant"]._update_available_quantity(
            product_5, self.stock_location, 2
        )
        self.env["stock.quant"]._update_available_quantity(
            product_6, self.stock_location, 10
        )

        delivery_1 = self._create_and_process_delivery_at_date(
            [(product_4, 6)], today, to_validate=False
        )
        delivery_1.date_planned = today + relativedelta(days=3)

        delivery_2 = self._create_and_process_delivery_at_date(
            [(product_5, 10)], today, to_validate=False
        )
        delivery_2.date_planned = today + relativedelta(days=5)

        self._create_and_process_delivery_at_date([(product_6, 10)], today)

        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=2),
        }
        self.assertEqual(product_4.with_context(context).qty_available_virtual, 1)
        self.assertEqual(product_5.with_context(context).qty_available_virtual, 2)
        self.assertEqual(product_6.with_context(context).qty_available_virtual, 0)

        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=4),
        }
        self.assertEqual(product_4.with_context(context).qty_available_virtual, -5)
        self.assertEqual(product_5.with_context(context).qty_available_virtual, 2)
        self.assertEqual(product_6.with_context(context).qty_available_virtual, 0)

        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=8),
        }
        self.assertEqual(product_4.with_context(context).qty_available_virtual, -5)
        self.assertEqual(product_5.with_context(context).qty_available_virtual, -8)
        self.assertEqual(product_6.with_context(context).qty_available_virtual, 0)

        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})

        self.assertEstimatedPrice(po, 810, based_on="actual_demand")
        self.assertEstimatedPrice(po, 1620, based_on="actual_demand", factor=200)
        self.assertEstimatedPrice(po, 450, based_on="actual_demand", days=4)
        self.assertEstimatedPrice(po, 270, based_on="actual_demand", days=4, factor=50)
        self.assertEstimatedPrice(po, 0, based_on="actual_demand", days=2)

        self.actionAddAll(po, based_on="actual_demand", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_4.id, "product_qty": 5},
                {"product_id": product_5.id, "product_qty": 8},
            ],
        )

        self.actionAddAll(po, based_on="actual_demand", days=30, factor=200)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_4.id, "product_qty": 10},
                {"product_id": product_5.id, "product_qty": 16},
            ],
        )

        self.actionAddAll(po, based_on="actual_demand", days=4, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_4.id, "product_qty": 5},
            ],
        )

        self.actionAddAll(po, based_on="actual_demand", days=4, factor=50)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_4.id, "product_qty": 3},
            ],
        )

    def test_purchase_order_suggest_quantities_for_consu(self):
        today = fields.Datetime.now()
        consu = self.env["product.product"].create(
            {
                "name": "Product Consu",
                "standard_price": 23,
            }
        )

        self.env["product.supplierinfo"].create(
            {
                "partner_id": self.vendor.id,
                "price": 20,
                "product_id": consu.id,
            }
        )

        self._create_and_process_delivery_at_date(
            [(consu, 55)], today - relativedelta(years=1, months=3)
        )
        self._create_and_process_delivery_at_date(
            [(consu, 12)], today - relativedelta(years=1)
        )
        self._create_and_process_delivery_at_date(
            [(consu, 5)], today - relativedelta(months=10, days=3)
        )
        self._create_and_process_delivery_at_date(
            [(consu, 5)], today - relativedelta(months=2, days=5)
        )
        self._create_and_process_delivery_at_date(
            [(consu, 10)], today - relativedelta(days=30)
        )
        self._create_and_process_delivery_at_date(
            [(consu, 10)], today - relativedelta(days=15)
        )

        self.assertEqual(consu.monthly_demand, 20)
        context = {"suggest_based_on": "one_week"}
        self.assertEqual(consu.with_context(context).monthly_demand, 0)
        context = {"suggest_based_on": "three_months"}
        self.assertAlmostEqual(
            consu.with_context(context).monthly_demand, 25 / 3, places=6
        )
        context = {"suggest_based_on": "one_year"}
        self.assertAlmostEqual(
            consu.with_context(context).monthly_demand, 42 / 12, places=6
        )
        context = {"suggest_based_on": "last_year"}
        self.assertEqual(consu.with_context(context).monthly_demand, 12)
        context = {"suggest_based_on": "last_year_m_plus_1"}
        self.assertEqual(consu.with_context(context).monthly_demand, 0)
        context = {"suggest_based_on": "last_year_m_plus_2"}
        self.assertEqual(consu.with_context(context).monthly_demand, 5)

        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        self.assertEstimatedPrice(po, 400)
        self.assertEstimatedPrice(po, 200, days=15)
        self.assertEstimatedPrice(po, 500, factor=125)
        self.assertEstimatedPrice(po, 180, based_on="three_months")
        self.assertEstimatedPrice(po, 500, based_on="three_months", days=90)
        self.assertEstimatedPrice(po, 80, based_on="one_year")
        self.assertEstimatedPrice(po, 840, based_on="one_year", days=365)

        self.actionAddAll(po, based_on="30_days", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": consu.id, "product_qty": 20},
            ],
        )
        self.actionAddAll(po, based_on="three_months", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": consu.id, "product_qty": 9},
            ],
        )
        self.actionAddAll(po, based_on="three_months", days=90, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": consu.id, "product_qty": 25},
            ],
        )

    def test_purchase_order_suggest_quantities_deduce_forecast_quantity(self):
        today = fields.Datetime.now()
        self.env["stock.quant"]._update_available_quantity(
            self.product_1, self.stock_location, 12
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 12)], date=today - relativedelta(days=10)
        )

        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})

        self.assertEstimatedPrice(po, 1200)
        self.actionAddAll(po, based_on="30_days", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 12},
            ],
        )

        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                            "product_id": self.product_1.id,
                            "product_uom_id": self.uom.id,
                            "product_uom_qty": 6,
                        }
                    )
                ],
            }
        )
        receipt.action_confirm()
        receipt.action_assign()
        self.assertEstimatedPrice(po, 600, days=30)
        self.actionAddAll(po, based_on="30_days", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 6},
            ],
        )

        product_ad = self.env["product.product"].create(
            [
                {
                    "name": "Product AD",
                    "standard_price": 60,
                    "is_storable": True,
                }
            ]
        )

        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "price": 55,
                    "product_id": product_ad.id,
                }
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            product_ad, self.stock_location, 7
        )

        delivery = self._create_and_process_delivery_at_date(
            [(product_ad, 12)], today, to_validate=False
        )
        delivery.date_planned = today + relativedelta(days=3)

        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        self.assertEstimatedPrice(po, 275, based_on="actual_demand", days=4)
        self.actionAddAll(po, based_on="actual_demand", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_ad.id, "product_qty": 5},
            ],
        )

        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                            "product_id": product_ad.id,
                            "product_uom_id": self.uom.id,
                            "product_uom_qty": 4,
                        }
                    )
                ],
            }
        )
        receipt.action_confirm()
        receipt.action_assign()

        self.assertEstimatedPrice(po, 55, based_on="actual_demand", days=4)
        self.actionAddAll(po, based_on="actual_demand", days=30, factor=100)
        self.assertRecordValues(
            po.line_ids,
            [
                {"product_id": product_ad.id, "product_qty": 1},
            ],
        )

    def test_purchase_order_suggest_quantities_multiwarehouse(self):
        date = fields.Datetime.now() - relativedelta(days=15)
        self.env["stock.quant"]._update_available_quantity(
            self.product_1, self.warehouse.lot_stock_id, 5
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_1, self.other_warehouse.lot_stock_id, 10
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 5)], date, warehouse=self.warehouse
        )
        self._create_and_process_delivery_at_date(
            [(self.product_1, 10)], date, warehouse=self.other_warehouse
        )
        self.assertEqual(self.product_1.monthly_demand, 15)
        self.assertEqual(
            self.product_1.with_context(warehouse_id=self.warehouse.id).monthly_demand,
            5,
        )
        self.assertEqual(
            self.product_1.with_context(
                warehouse_id=self.other_warehouse.id
            ).monthly_demand,
            10,
        )

        po_1 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "picking_type_id": self.warehouse.in_type_id.id,
            }
        )
        self.assertEstimatedPrice(po_1, 500, warehouse=self.warehouse)
        self.assertEstimatedPrice(po_1, 1000, warehouse=self.other_warehouse)
        self.actionAddAll(
            po_1, based_on="30_days", days=30, factor=100, warehouse=self.warehouse
        )
        self.assertRecordValues(
            po_1.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 5},
            ],
        )
        self.actionAddAll(
            po_1,
            based_on="30_days",
            days=30,
            factor=100,
            warehouse=self.other_warehouse,
        )
        self.assertRecordValues(
            po_1.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 10},
            ],
        )

        po_2 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "picking_type_id": self.other_warehouse.in_type_id.id,
            }
        )
        self.assertEstimatedPrice(po_2, 500, warehouse=self.warehouse)
        self.assertEstimatedPrice(po_2, 1000, warehouse=self.other_warehouse)
        self.actionAddAll(
            po_2,
            based_on="30_days",
            days=30,
            factor=100,
            warehouse=self.other_warehouse,
        )
        self.assertRecordValues(
            po_2.line_ids,
            [
                {"product_id": self.product_1.id, "product_qty": 10},
            ],
        )

        product_ad = self.env["product.product"].create(
            [
                {
                    "name": "Product AD",
                    "standard_price": 60,
                    "is_storable": True,
                }
            ]
        )

        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "price": 55,
                    "product_id": product_ad.id,
                }
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            product_ad, self.warehouse.lot_stock_id, 7
        )
        self.env["stock.quant"]._update_available_quantity(
            product_ad, self.other_warehouse.lot_stock_id, 5
        )

        today = fields.Datetime.now()
        delivery_1 = self._create_and_process_delivery_at_date(
            [(product_ad, 10)], today, to_validate=False, warehouse=self.warehouse
        )
        delivery_1.date_planned = today + relativedelta(days=3)

        delivery_2 = self._create_and_process_delivery_at_date(
            [(product_ad, 9)], today, to_validate=False, warehouse=self.other_warehouse
        )
        delivery_2.date_planned = today + relativedelta(days=5)

        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=6),
        }
        self.assertEqual(product_ad.with_context(context).qty_available_virtual, -7)
        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=6),
            "warehouse_id": self.warehouse.id,
        }
        self.assertEqual(product_ad.with_context(context).qty_available_virtual, -3)
        context = {
            "to_date": fields.Datetime.now() + relativedelta(days=6),
            "warehouse_id": self.other_warehouse.id,
        }
        self.assertEqual(product_ad.with_context(context).qty_available_virtual, -4)

        po_1 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "picking_type_id": self.warehouse.in_type_id.id,
            }
        )
        self.assertEstimatedPrice(
            po_1, 165, based_on="actual_demand", warehouse=self.warehouse
        )
        self.assertEstimatedPrice(
            po_1, 220, based_on="actual_demand", warehouse=self.other_warehouse
        )

        self.actionAddAll(
            po_1,
            based_on="actual_demand",
            days=30,
            factor=100,
            warehouse=self.other_warehouse,
        )
        self.assertRecordValues(
            po_1.line_ids,
            [
                {"product_id": product_ad.id, "product_qty": 4},
            ],
        )
        self.actionAddAll(
            po_1,
            based_on="actual_demand",
            days=30,
            factor=100,
            warehouse=self.warehouse,
        )
        self.assertRecordValues(
            po_1.line_ids,
            [
                {"product_id": product_ad.id, "product_qty": 3},
            ],
        )

        po_2 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "picking_type_id": self.other_warehouse.in_type_id.id,
            }
        )
        self.assertEstimatedPrice(
            po_2, 165, based_on="actual_demand", warehouse=self.warehouse
        )
        self.assertEstimatedPrice(
            po_2, 220, based_on="actual_demand", warehouse=self.other_warehouse
        )

    def test_purchase_order_suggest_pricelist_selection(self):
        today = fields.Datetime.now()
        po = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        product = self.env["product.product"].create(
            {
                "name": "Product 7",
                "standard_price": 20,
                "is_storable": True,
            }
        )
        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "price": 17,
                    "product_id": product.id,
                    "min_qty": 2,
                },
                {
                    "partner_id": self.vendor.id,
                    "price": 13,
                    "product_id": product.id,
                    "min_qty": 3,
                },
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 1
        )
        self._create_and_process_delivery_at_date(
            [(product, 1)], today - relativedelta(days=1)
        )
        self.assertEstimatedPrice(po, 17, based_on="one_week", days=7)
        self.assertEstimatedPrice(po, 34, based_on="one_week", days=14)
        self.assertEstimatedPrice(po, 52, based_on="one_week", days=28)

        partner_2 = self.env["res.partner"].create({"name": "No pricelist"})
        po_2 = self.env["purchase.order"].create({"partner_id": partner_2.id})
        self.assertEstimatedPrice(po_2, 20, based_on="one_week", days=7)

    def test_purchase_order_suggest_search_panel_ux(self):
        today = fields.Datetime.now()
        test_category = self.env["product.category"].create(
            {
                "name": "Test Category",
            }
        )
        test_category_goods = self.env["product.category"].create(
            {
                "name": "Goods",
            }
        )
        self.product_1.categ_id = test_category_goods.id
        test_product = self.env["product.product"].create(
            [
                {
                    "name": "test_product",
                    "categ_id": test_category.id,
                    "is_storable": True,
                }
            ]
        )
        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "min_qty": 1,
                    "price": 20,
                    "product_id": test_product.id,
                }
            ]
        )

        self.env["stock.quant"]._update_available_quantity(
            test_product, self.stock_location, 24
        )
        self._create_and_process_delivery_at_date(
            [(test_product, 12)], date=fields.Datetime.now() - relativedelta(days=1)
        )
        self._create_and_process_delivery_at_date(
            [(test_product, 12)], date=fields.Datetime.now() - relativedelta(days=10)
        )
        self.assertEqual(test_product.monthly_demand, 24)

        self._create_and_process_delivery_at_date(
            [(test_product, 50)], date=today + relativedelta(days=18), to_validate=False
        )
        self._create_and_process_delivery_at_date(
            [(test_product, 50)], date=today + relativedelta(days=20), to_validate=False
        )
        other_warehouse = self.other_warehouse
        self.env["stock.quant"]._update_available_quantity(
            test_product, other_warehouse.lot_stock_id, 1
        )
        self._create_and_process_delivery_at_date(
            [(test_product, 1)],
            date=today - relativedelta(days=1),
            warehouse=other_warehouse,
        )
        self.start_tour(
            "/odoo/purchases",
            "test_purchase_order_suggest_search_panel_ux",
            login="admin",
        )
