# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged


class TestAnalyticAccount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The group 'mrp.group_mrp_routings' is required to make the field
        # 'workorder_ids' visible in the view of 'mrp.production'. The subviews
        #  of `workorder_ids` must be present in many tests to create records.
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
        cls.product = cls.env["product.product"].create(
            {
                "name": "Product",
                "is_storable": True,
                "standard_price": 233.0,
            }
        )

    def test_mandatory_analytic_plan_bom(self):
        """
        Tests that the distribution validation is correctly evaluated
        The BOM creation should not be constrained by any analytic applicability rule.
        """
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.product.product_tmpl_id.id,
            }
        )
        self.assertTrue(bom)

        self.applicability.business_domain = "manufacturing_order"

        bom_2 = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.product.product_tmpl_id.id,
            }
        )
        self.assertTrue(bom_2)

    def test_mandatory_analytic_plan_workcenter(self):
        """
        Tests that the distribution validation is correctly evaluated
        The Workcenter creation should not be constrained by any analytic applicability rule.
        """
        workcenter = self.env["mrp.workcenter"].create(
            {
                "name": "Great Workcenter",
                "analytic_distribution": False,
            }
        )
        self.assertTrue(workcenter)

        self.applicability.business_domain = "manufacturing_order"

        workcenter_2 = self.env["mrp.workcenter"].create(
            {
                "name": "Great Workcenter",
                "analytic_distribution": False,
            }
        )
        self.assertTrue(workcenter_2)


@tagged("post_install", "-at_install")
class TestAnalyticAccountSmartButtons(TransactionCase):
    """Counters and smart-button actions of manufacturing analytic accounts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("analytic.group_analytic_accounting")
        plan = cls.env["account.analytic.plan"].create({"name": "MRP plan"})
        cls.account = cls.env["account.analytic.account"].create(
            {"name": "MRP analytic account", "plan_id": plan.id},
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Analytic product", "is_storable": True},
        )
        cls.component = cls.env["product.product"].create(
            {"name": "Analytic component", "is_storable": True},
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.product.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
            },
        )
        # production_ids / bom_ids are plain many2many on the account side:
        # link from there instead of through a non-existent inverse field.
        cls.account.bom_ids = [Command.link(cls.bom.id)]

    def _make_production(self):
        production = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "product_qty": 1.0,
                "bom_id": self.bom.id,
            },
        )
        production.action_confirm()
        self.account.production_ids = [Command.link(production.id)]
        return production

    def test_counters_reflect_linked_records(self):
        """The BoM and production counters follow their linked records."""
        self.assertEqual(self.account.bom_count, 1)
        self.assertEqual(self.account.production_count, 0)

        self._make_production()

        self.account.invalidate_recordset(["production_count"])
        self.assertEqual(self.account.production_count, 1)

    def test_single_record_actions_open_the_form(self):
        """With one linked record the action opens it directly in form view."""
        production = self._make_production()

        bom_action = self.account.action_view_mrp_bom()
        self.assertEqual(bom_action["view_mode"], "form")
        self.assertEqual(bom_action["res_id"], self.bom.id)

        mo_action = self.account.action_view_mrp_production()
        self.assertEqual(mo_action["view_mode"], "form")
        self.assertEqual(mo_action["res_id"], production.id)

    def test_multi_record_action_opens_the_list(self):
        """With several linked records the action falls back to the list."""
        first = self._make_production()
        second = self._make_production()

        action = self.account.action_view_mrp_production()

        self.assertEqual(action["view_mode"], "list,form")
        self.assertCountEqual(action["domain"][0][2], (first | second).ids)
        self.assertEqual(
            action["context"]["default_analytic_account_id"], self.account.id
        )


@tagged("post_install", "-at_install")
class TestWipEntryProductionLinks(TransactionCase):
    """WIP journal entries keep, count and open their source MOs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "WIP product", "is_storable": True},
        )
        cls.component = cls.env["product.product"].create(
            {"name": "WIP component", "is_storable": True},
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.product.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
            },
        )
        cls.productions = cls.env["mrp.production"].create(
            [
                {
                    "product_id": cls.product.id,
                    "product_qty": 1.0,
                    "bom_id": cls.bom.id,
                },
                {
                    "product_id": cls.product.id,
                    "product_qty": 2.0,
                    "bom_id": cls.bom.id,
                },
            ],
        )
        cls.entry = cls.env["account.move"].create({"move_type": "entry"})

    def test_count_follows_linked_productions(self):
        """The counter tracks the MOs the WIP entry was based on."""
        self.assertEqual(self.entry.wip_production_count, 0)

        self.entry.wip_production_ids = [Command.set(self.productions.ids)]

        self.assertEqual(self.entry.wip_production_count, 2)

    def test_links_survive_duplication(self):
        """Copying a WIP entry carries its source MOs over."""
        self.entry.wip_production_ids = [Command.set(self.productions.ids)]

        copied = self.entry.copy()

        self.assertEqual(copied.wip_production_ids, self.productions)

    def test_action_opens_form_or_list_by_count(self):
        """One MO opens in form, several open as a named list."""
        self.entry.wip_production_ids = [Command.set(self.productions[0].ids)]
        single = self.entry.action_view_wip_production()
        self.assertEqual(single["view_mode"], "form")
        self.assertEqual(single["res_id"], self.productions[0].id)

        self.entry.wip_production_ids = [Command.set(self.productions.ids)]
        multi = self.entry.action_view_wip_production()
        self.assertEqual(multi["view_mode"], "list,form")
        self.assertCountEqual(multi["domain"][0][2], self.productions.ids)
        self.assertIn(self.entry.name or "", multi["name"])
