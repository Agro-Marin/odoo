from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase


class TestMrpAnalyticAccount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref(
            "analytic.group_analytic_accounting"
        ) + cls.env.ref("mrp.group_mrp_routings")
        cls.analytic_plan = cls.env["account.analytic.plan"].create(
            {
                "name": "Plan",
            }
        )
        cls.applicability = cls.env["account.analytic.applicability"].create(
            {
                "business_domain": "general",
                "analytic_plan_id": cls.analytic_plan.id,
                "applicability": "mandatory",
            }
        )
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {
                "name": "test_analytic_account",
                "plan_id": cls.analytic_plan.id,
            }
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {
                "name": "Workcenter",
                "time_efficiency": 100,
                "costs_hour": 10,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Product",
                "is_storable": True,
                "standard_price": 233.0,
            }
        )
        cls.component = cls.env["product.product"].create(
            {
                "name": "Component",
                "is_storable": True,
                "standard_price": 10.0,
            }
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_id": cls.product.id,
                "product_tmpl_id": cls.product.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    (0, 0, {"product_id": cls.component.id, "product_qty": 1.0}),
                ],
                "operation_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "work work",
                            "workcenter_id": cls.workcenter.id,
                            "time_cycle": 15,
                            "sequence": 1,
                        },
                    ),
                ],
            }
        )
        cls.project = cls.env["project.project"].create(
            {
                "name": "Test Projet",
                f"{cls.analytic_plan._column_name()}": cls.analytic_account.id,
            }
        )
        cls.project.account_id = False


class TestAnalyticAccount(TestMrpAnalyticAccount):
    def test_mo_analytic(self):
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 10.0
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 0)
        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.save()
        self.assertEqual(mo.state, "progress")
        self.assertEqual(mo.move_raw_ids.analytic_account_line_ids.amount, -50.0)

        mo_form = Form(mo)
        mo_form.qty_producing = 10.0
        mo_form.save()
        mo.workorder_ids.button_finish()
        self.assertEqual(mo.state, "to_close")
        self.assertEqual(mo.move_raw_ids.analytic_account_line_ids.amount, -100.0)

        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.analytic_account_line_ids.amount, -100.0)

    def test_mo_analytic_backorder(self):
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 10.0
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 0)

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.save()
        self.assertEqual(mo.state, "progress")
        self.assertEqual(mo.move_raw_ids.analytic_account_line_ids.amount, -50.0)

        Form.from_action(self.env, mo.button_mark_done()).save().action_backorder()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.analytic_account_line_ids.amount, -50.0)

    def test_workcenter_different_analytic_account(self):
        self.env.user.group_ids += self.env.ref("mrp.group_mrp_routings")
        analytic_plan = self.env["account.analytic.plan"].create({"name": "Plan Test"})
        wc_analytic_account = self.env["account.analytic.account"].create(
            {"name": "wc_analytic_account", "plan_id": analytic_plan.id}
        )
        self.workcenter.analytic_distribution = {str(wc_analytic_account.id): 100.0}

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 10.0
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(len(mo.workorder_ids.wc_analytic_account_line_ids), 0)

        mo.workorder_ids[0].duration = 60.0
        self.assertEqual(mo.workorder_ids.mo_analytic_account_line_ids.amount, -10.0)
        self.assertEqual(
            mo.workorder_ids.mo_analytic_account_line_ids[
                self.analytic_plan._column_name()
            ],
            self.analytic_account,
        )
        self.assertEqual(mo.workorder_ids.wc_analytic_account_line_ids.amount, -10.0)
        self.assertEqual(
            mo.workorder_ids.wc_analytic_account_line_ids[analytic_plan._column_name()],
            wc_analytic_account,
        )

        mo.workorder_ids[0].duration = 120.0
        self.assertEqual(mo.workorder_ids.mo_analytic_account_line_ids.amount, -20.0)
        self.assertEqual(
            mo.workorder_ids.mo_analytic_account_line_ids[
                self.analytic_plan._column_name()
            ],
            self.analytic_account,
        )
        self.assertEqual(mo.workorder_ids.wc_analytic_account_line_ids.amount, -20.0)
        self.assertEqual(
            mo.workorder_ids.wc_analytic_account_line_ids[analytic_plan._column_name()],
            wc_analytic_account,
        )

        mo.qty_producing = 10.0
        mo.set_qty_producing()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.workorder_ids.mo_analytic_account_line_ids.amount, -20.0)
        self.assertEqual(
            mo.workorder_ids.mo_analytic_account_line_ids[
                self.analytic_plan._column_name()
            ],
            self.analytic_account,
        )
        self.assertEqual(mo.workorder_ids.wc_analytic_account_line_ids.amount, -20.0)
        self.assertEqual(
            mo.workorder_ids.wc_analytic_account_line_ids[analytic_plan._column_name()],
            wc_analytic_account,
        )

    def test_changing_mo_analytic_account(self):
        self.env.user.group_ids += self.env.ref("mrp.group_mrp_routings")
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 1
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 0)
        self.assertEqual(len(mo.workorder_ids.mo_analytic_account_line_ids), 0)

        mo.workorder_ids[0].duration = 60.0
        self.assertEqual(
            mo.workorder_ids.mo_analytic_account_line_ids[
                self.analytic_plan._column_name()
            ],
            self.analytic_account,
        )

        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 1)

        analytic_plan = self.env["account.analytic.plan"].create({"name": "Plan Test"})
        new_analytic_account = self.env["account.analytic.account"].create(
            {"name": "test_analytic_account_2", "plan_id": analytic_plan.id}
        )
        new_project = self.env["project.project"].create(
            {
                "name": "New Project",
                f"{analytic_plan._column_name()}": new_analytic_account.id,
            }
        )
        new_project.account_id = False
        mo.project_id = new_project
        self.assertEqual(
            mo.move_raw_ids.analytic_account_line_ids[analytic_plan._column_name()],
            new_analytic_account,
        )
        self.assertEqual(
            mo.workorder_ids.mo_analytic_account_line_ids[analytic_plan._column_name()],
            new_analytic_account,
        )

        mo_analytic_account_raw_lines = mo.move_raw_ids.analytic_account_line_ids
        mo_analytic_account_wc_lines = mo.move_raw_ids.analytic_account_line_ids
        mo.project_id = False
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 0)
        self.assertEqual(len(mo.workorder_ids.mo_analytic_account_line_ids), 0)
        self.assertFalse(mo_analytic_account_raw_lines.exists())
        self.assertFalse(mo_analytic_account_wc_lines.exists())
        mo.project_id = self.project
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 1)
        self.assertEqual(len(mo.workorder_ids.mo_analytic_account_line_ids), 1)

    def test_add_remove_wo_analytic_no_company(self):
        analytic_account_no_company = (
            self.env["account.analytic.account"]
            .create(
                {
                    "name": "test_analytic_account_no_company",
                    "plan_id": self.analytic_plan.id,
                }
            )
            .with_context(analytic_plan_id=self.analytic_plan.id)
        )
        analytic_account_no_company.company_id = False
        project_aa_no_company = self.env["project.project"].create(
            {
                "name": "Project AA No Company",
                f"{self.analytic_plan._column_name()}": analytic_account_no_company.id,
            }
        )
        project_aa_no_company.account_id = False

        mo_no_company = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "project_id": project_aa_no_company.id,
                "product_uom_id": self.bom.product_uom_id.id,
            }
        )

        mo_no_c_form = Form(mo_no_company)
        wo = self.env["mrp.workorder"].create(
            {
                "name": "Work_order",
                "workcenter_id": self.workcenter.id,
                "product_uom_id": self.bom.product_uom_id.id,
                "production_id": mo_no_c_form.id,
                "duration": 60,
            }
        )
        mo_no_c_form.save()
        self.assertTrue(mo_no_company.workorder_ids)
        self.assertEqual(
            wo.production_id.project_id._get_analytic_accounts(),
            analytic_account_no_company,
        )
        self.assertEqual(len(analytic_account_no_company.line_ids), 1)
        mo_no_company.workorder_ids.unlink()
        self.assertEqual(len(analytic_account_no_company.line_ids), 0)

    def test_update_components_qty_to_0(self):
        component = self.env["product.product"].create(
            {
                "name": "Component",
                "is_storable": True,
                "standard_price": 100,
            }
        )
        product = self.env["product.product"].create(
            {
                "name": "Product",
                "is_storable": True,
            }
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "product_uom_id": product.uom_id.id,
                "type": "normal",
                "bom_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": component.id,
                            "product_qty": 1,
                            "product_uom_id": component.uom_id.id,
                        },
                    )
                ],
            }
        )
        analytic_account = self.env["account.analytic.account"].create(
            {
                "name": "Test Account",
                "plan_id": self.analytic_plan.id,
            }
        )
        new_project = self.env["project.project"].create(
            {
                "name": "New project",
                f"{self.analytic_plan._column_name()}": analytic_account.id,
            }
        )
        new_project.account_id = False

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo_form.bom_id = bom
        mo_form.product_qty = 1.0
        mo_form.project_id = new_project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")

        mo_form = Form(mo)
        mo_form.qty_producing = 1
        mo = mo_form.save()
        self.assertEqual(mo.state, "to_close")
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(analytic_account.debit, 100)
        mo.move_raw_ids[0].quantity = 0
        self.assertEqual(analytic_account.debit, 0)
        self.assertFalse(analytic_account.line_ids)

    def test_cross_analytics(self):
        ap1 = self.env["account.analytic.plan"].create(
            {
                "name": "Plan 1",
            }
        )
        ap2 = self.env["account.analytic.plan"].create(
            {
                "name": "Plan 2",
            }
        )
        ac1 = self.env["account.analytic.account"].create(
            {
                "name": "Account in Plan 1",
                "plan_id": ap1.id,
            }
        )
        ac2 = self.env["account.analytic.account"].create(
            {
                "name": "Account in Plan 2",
                "plan_id": ap2.id,
            }
        )
        ap1_column = ap1._column_name()
        ap2_column = ap2._column_name()
        new_project = self.project.create(
            {
                "name": "Cross Analytics Project",
                ap1_column: ac1.id,
                ap2_column: ac2.id,
            }
        )

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 10.0
        mo_form.project_id = new_project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(len(mo.move_raw_ids.analytic_account_line_ids), 0)

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.save()
        self.assertEqual(mo.state, "progress")
        aal = mo.move_raw_ids.analytic_account_line_ids
        self.assertEqual(len(aal), 1)
        self.assertEqual(sum(aal.mapped("amount")), -50.00)

        mo_form = Form(mo)
        mo_form.qty_producing = 10.0
        mo_form.save()
        mo.workorder_ids.button_finish()
        aal = mo.move_raw_ids.analytic_account_line_ids

        self.assertEqual(mo.state, "to_close")
        self.assertEqual(len(aal), 1)
        self.assertEqual(sum(aal.mapped("amount")), -100.00)

        mo.button_mark_done()
        aal = mo.move_raw_ids.analytic_account_line_ids
        self.assertEqual(mo.state, "done")
        self.assertEqual(len(aal), 1)
        self.assertEqual(sum(aal.mapped("amount")), -100.00)

        self.assertEqual(aal[ap1_column], ac1)
        self.assertEqual(aal[ap2_column], ac2)

    def test_mo_qty_analytics(self):
        location = self.env.ref("stock.stock_location_stock")
        self.env["stock.quant"]._update_available_quantity(self.component, location, 10)

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 10.0
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(self.analytic_account.balance, 0.0)

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.save()
        self.assertEqual(mo.state, "progress")
        self.assertEqual(self.analytic_account.balance, -50.0)

        mo_form = Form(mo)
        mo_form.qty_producing = 0.0
        mo_form.save()
        self.assertEqual(mo.state, "progress")
        self.assertEqual(self.analytic_account.balance, 0.0)

    def test_mandatory_analytic_plan_production(self):
        self.env.user.group_ids += self.env.ref("mrp.group_mrp_routings")
        self.applicability.business_domain = "manufacturing_order"
        self.project[f"{self.analytic_plan._column_name()}"] = False
        new_analytic_plan = self.env["account.analytic.plan"].create(
            {
                "name": "New Plan",
            }
        )
        new_analytic_account = self.env["account.analytic.account"].create(
            {
                "name": "New Analytic Account",
                "plan_id": new_analytic_plan.id,
            }
        )
        self.project[f"{new_analytic_plan._column_name()}"] = new_analytic_account

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 1
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        self.assertTrue(mo)

        with self.assertRaises(ValidationError):
            mo.button_mark_done()

    def test_bom_aal_generation(self):

        self.env.user.group_ids += self.env.ref("mrp.group_mrp_routings")

        self.bom.project_id = self.project
        self.bom.bom_line_ids.operation_id = self.bom.operation_ids
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 1
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        mo.workorder_ids.button_finish()
        bom_analytic_lines = mo.move_raw_ids.analytic_account_line_ids
        self.assertEqual(len(bom_analytic_lines), 1)
        self.assertEqual(bom_analytic_lines.category, "manufacturing_order")
        mo.button_mark_done()
        self.assertEqual(bom_analytic_lines, mo.move_raw_ids.analytic_account_line_ids)

    def test_category_analytic_line_mrp(self):

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product
        mo_form.bom_id = self.bom
        mo_form.product_qty = 1
        mo_form.project_id = self.project
        mo = mo_form.save()
        mo.action_confirm()
        mo.button_mark_done()
        self.assertEqual(
            mo.move_raw_ids.analytic_account_line_ids.category, "manufacturing_order"
        )
