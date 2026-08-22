from unittest.mock import patch

from odoo import SUPERUSER_ID
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.ir_cron import IrCron
from odoo.addons.stock.models.stock_orderpoint import StockWarehouseOrderpoint


class TestOrderpointSchedulerContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref("stock.warehouse0")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Scheduler Contract Product",
                "type": "consu",
                "is_storable": True,
            }
        )
        cls.orderpoint = cls.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": cls.product.id,
                "location_id": cls.stock_location.id,
                "product_min_qty": 5.0,
                "product_max_qty": 5.0,
            }
        )

    def _read_stored_qty_to_order(self, cr):
        cr.execute(
            "SELECT qty_to_order_computed FROM stock_warehouse_orderpoint"
            " WHERE id = %s",
            [self.orderpoint.id],
        )
        return cr.fetchone()[0]

    def test_scheduler_flushes_recomputes_before_procurement(self):
        self.env.flush_all()
        self.assertAlmostEqual(self._read_stored_qty_to_order(self.env.cr), 5.0)

        move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 3.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        self.env.flush_all()
        self.assertAlmostEqual(self._read_stored_qty_to_order(self.env.cr), 8.0)

        self.env.cr.execute(
            "UPDATE stock_warehouse_orderpoint SET qty_to_order_computed = 1.0"
            " WHERE id = %s",
            [self.orderpoint.id],
        )
        self.env.invalidate_all()
        self.assertAlmostEqual(self._read_stored_qty_to_order(self.env.cr), 1.0)

        captured = {}
        procure_orderpoint_confirm = (
            StockWarehouseOrderpoint._procure_orderpoint_confirm
        )

        def _probing_procure(records, *args, **kwargs):
            captured["flushed_qty"] = self._read_stored_qty_to_order(records.env.cr)
            return procure_orderpoint_confirm(records, *args, **kwargs)

        self.registry_enter_test_mode()
        with self.registry.cursor() as scheduler_cr:
            scheduler_env = self.env(cr=scheduler_cr)
            with patch.object(
                StockWarehouseOrderpoint,
                "_procure_orderpoint_confirm",
                _probing_procure,
            ):
                scheduler_env["stock.scheduler"]._run_tasks(use_new_cursor=True)

        self.assertAlmostEqual(
            captured.get("flushed_qty"),
            8.0,
            msg="The scheduler must flush/commit the freshly recomputed "
            "qty_to_order_computed before _procure_orderpoint_confirm opens "
            "its batch cursors; procuring on the previous run's committed "
            "value delays replenishments, and the late flush of the "
            "pre-procurement snapshot then clobbers the post-procurement "
            "value, causing duplicate orders on the next run.",
        )

    def test_scheduler_commits_between_recomputes_and_procurement(self):
        calls = []
        commit_progress = IrCron._commit_progress
        compute_lead_time_stats = StockWarehouseOrderpoint._compute_lead_time_stats

        def _record_commit(records, *args, **kwargs):
            calls.append("commit")
            return commit_progress(records, *args, **kwargs)

        def _record_lead_stats(records, *args, **kwargs):
            calls.append("lead_stats")
            return compute_lead_time_stats(records, *args, **kwargs)

        def _record_procure(records, *args, **kwargs):
            calls.append("procure")
            return {}

        self.registry_enter_test_mode()
        with self.registry.cursor() as scheduler_cr:
            scheduler_env = self.env(cr=scheduler_cr)
            with (
                patch.object(IrCron, "_commit_progress", _record_commit),
                patch.object(
                    StockWarehouseOrderpoint,
                    "_compute_lead_time_stats",
                    _record_lead_stats,
                ),
                patch.object(
                    StockWarehouseOrderpoint,
                    "_procure_orderpoint_confirm",
                    _record_procure,
                ),
            ):
                scheduler_env["stock.scheduler"]._run_tasks(use_new_cursor=True)

        self.assertIn("lead_stats", calls)
        self.assertIn("procure", calls)
        lead_stats_index = calls.index("lead_stats")
        procure_index = calls.index("procure")
        self.assertTrue(
            any(
                name == "commit" and lead_stats_index < index < procure_index
                for index, name in enumerate(calls)
            ),
            "A progress commit must happen between the stored recomputes and "
            "_procure_orderpoint_confirm so the batch cursors see fresh values "
            f"(recorded call sequence: {calls}).",
        )


@tagged("post_install", "-at_install")
class TestOrderpointActivity(TransactionCase):
    def test_orderpoint_activity_portal_context_leak(self):
        company_b = self.env["res.company"].search(
            [("id", "!=", self.env.company.id)], limit=1
        )
        if not company_b:
            self.env.user.lang = "en_US"
            company_b = self.env["res.company"].create(
                {"name": "Thanks to Nature Test"}
            )

        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", company_b.id)], limit=1
        )
        if not warehouse_b:
            warehouse_b = self.env["stock.warehouse"].create(
                {
                    "name": "Website WH",
                    "code": "WWH",
                    "company_id": company_b.id,
                }
            )

        shared_product = self.env["product.product"].create(
            {
                "name": "Shared Product",
                "type": "consu",
                "is_storable": True,
                "company_id": False,
            }
        )

        portal_user = self.env["res.users"].create(
            {
                "name": "Portal Customer",
                "login": "portal_customer_nature_leak_test",
                "email": "customer@naturetest.com",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
                "company_id": company_b.id,
                "company_ids": [Command.set([company_b.id])],
            }
        )

        isolated_location = self.env["stock.location"].create(
            {
                "name": "Isolated Replenish Location",
                "usage": "internal",
                "company_id": company_b.id,
            }
        )

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "name": "Failing Routing Rule",
                "product_id": shared_product.id,
                "warehouse_id": warehouse_b.id,
                "location_id": isolated_location.id,
                "product_min_qty": 0,
                "product_max_qty": 0,
                "trigger": "auto",
                "company_id": company_b.id,
            }
        )
        orderpoint.write(
            {
                "product_min_qty": 10.0,
                "product_max_qty": 10.0,
            }
        )

        orderpoint.with_user(portal_user).sudo()._procure_orderpoint_confirm(
            company_id=company_b.id, raise_user_error=False
        )

        activity = self.env["mail.activity"].search(
            [
                ("res_model", "in", ["product.template", "product.product"]),
                (
                    "res_id",
                    "in",
                    [shared_product.product_tmpl_id.id, shared_product.id],
                ),
                (
                    "activity_type_id",
                    "=",
                    self.env.ref("mail.mail_activity_data_warning").id,
                ),
            ],
            limit=1,
        )

        self.assertTrue(
            activity,
            "An exception activity should have been created on the product template.",
        )
        self.assertEqual(
            activity.create_uid.id,
            SUPERUSER_ID,
            "The activity creator leaked: it must be created by OdooBot, not "
            "the triggering (portal) user.",
        )
