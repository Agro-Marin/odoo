"""Work order behaviour that had no test until it was found broken.

Each test here pins one defect and fails without its fix.  Where two readings
of a rule were possible the test says which one is the rule and why, because
the other reading is the one someone will reach for next.
"""

from datetime import datetime

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWorkorderAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["mrp.workcenter"].search([]).write({"working_state": "normal"})
        cls.wc = cls.env["mrp.workcenter"].create(
            {"name": "AUD WC", "time_efficiency": 100, "costs_hour": 10}
        )
        cls.wc2 = cls.env["mrp.workcenter"].create(
            {"name": "AUD WC2", "time_efficiency": 100, "costs_hour": 10}
        )

    def _mo(self, n_ops=1, qty=5, tag="T"):
        fin = self.env["product.product"].create(
            {"name": f"{tag} fin", "is_storable": True}
        )
        comp = self.env["product.product"].create(
            {"name": f"{tag} comp", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": fin.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": comp.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": f"Op{i}",
                            "workcenter_id": self.wc.id,
                            "time_cycle_manual": 10,
                            "sequence": (i + 1) * 5,
                        }
                    )
                    for i in range(n_ops)
                ],
            }
        )
        mo = self.env["mrp.production"].create(
            {"product_id": fin.id, "bom_id": bom.id, "product_qty": qty}
        )
        mo.action_confirm()
        self.env.flush_all()
        return mo

    # ------------------------------------------------------------------
    def test_replanning_an_unconflicted_workorder_keeps_its_slot(self):
        """Replan must be idempotent: a work order does not collide with itself."""
        mo = self._mo(tag="R")
        mo.button_plan()
        self.env.flush_all()
        wo = mo.workorder_ids
        planned = (wo.date_start, wo.date_end)
        wo.action_replan()
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(
            (wo.date_start, wo.date_end),
            planned,
            "replanning a work order that conflicts with nothing moved it",
        )

    def test_pausing_many_workorders_closes_every_timer(self):
        mo = self._mo(n_ops=3, tag="P")
        mo.workorder_ids.button_start()
        self.env.flush_all()
        productivity = self.env["mrp.workcenter.productivity"]
        domain = [
            ("workorder_id", "in", mo.workorder_ids.ids),
            ("date_end", "=", False),
        ]
        self.assertEqual(productivity.search_count(domain), 3)
        mo.workorder_ids.button_pending()
        self.env.flush_all()
        self.assertEqual(
            productivity.search_count(domain),
            0,
            "button_pending on a recordset closed only some of the timers",
        )

    def test_is_user_working_is_per_user(self):
        mo = self._mo(tag="U")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        other = self.env["res.users"].create(
            {
                "name": "Audit Other",
                "login": "audit_other_user",
                "group_ids": [Command.link(self.env.ref("base.group_user").id)],
            }
        )
        self.assertTrue(wo.is_user_working)
        self.assertFalse(
            wo.with_user(other).is_user_working,
            "is_user_working leaked another user's timer (no depends_context('uid'))",
        )

    def test_is_user_working_refreshes_after_starting(self):
        mo = self._mo(tag="W")
        wo = mo.workorder_ids
        self.assertFalse(wo.is_user_working)
        wo.button_start()
        self.env.flush_all()
        self.assertTrue(
            wo.is_user_working,
            "is_user_working is stale after button_start (no @api.depends)",
        )

    def test_scrap_count_refreshes(self):
        mo = self._mo(tag="S")
        wo = mo.workorder_ids
        self.assertEqual(wo.scrap_count, 0)
        component = mo.move_raw_ids[0].product_id
        self.env["stock.scrap"].create(
            {
                "product_id": component.id,
                "product_uom_id": component.uom_id.id,
                "scrap_qty": 1,
                "workorder_id": wo.id,
                "production_id": mo.id,
                "company_id": mo.company_id.id,
            }
        )
        self.env.flush_all()
        self.assertEqual(
            wo.scrap_count, 1, "scrap_count is stale (no @api.depends('scrap_ids'))"
        )

    def test_qty_ready_is_zero_once_cancelled(self):
        mo = self._mo(tag="Q")
        wo = mo.workorder_ids
        self.assertGreater(wo.qty_ready, 0)
        wo.action_cancel()
        self.env.flush_all()
        self.assertEqual(
            wo.qty_ready, 0, "qty_ready is stale after a state change (missing depends)"
        )

    def test_duration_unit_for_a_fractional_quantity(self):
        mo = self._mo(tag="D")
        wo = mo.workorder_ids
        wo.write({"duration": 60.0})
        self.env.flush_all()
        wo.write({"qty_produced": 0.5})
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_unit,
            120.0,
            places=2,
            msg="duration_unit divides by max(qty_produced, 1)",
        )

    def test_duration_expected_scales_on_a_started_workorder(self):
        mo = self._mo(tag="C")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        before = wo.duration_expected
        self.env["change.production.qty"].create(
            {"mo_id": mo.id, "product_qty": 20}
        ).change_prod_qty()
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_expected,
            before * 4,
            places=2,
            msg="quadrupling the quantity left a started work order's duration frozen",
        )

    def test_time_efficiency_applies_without_an_operation(self):
        mo = self._mo(tag="E")
        wo = mo.workorder_ids
        wo.operation_id = False
        wo.workcenter_id = self.wc
        wo.duration_expected = 100
        self.env.flush_all()
        self.wc2.resource_id.time_efficiency = 200
        wo.write({"workcenter_id": self.wc2.id})
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_expected,
            50.0,
            places=2,
            msg="a twice-as-fast work center did not change the expected duration",
        )

    def test_an_operation_added_later_keeps_the_routing_order(self):
        mo = self._mo(n_ops=3, tag="O")
        self.env["mrp.routing.workcenter"].create(
            {
                "name": "Prep",
                "bom_id": mo.bom_id.id,
                "sequence": 1,
                "workcenter_id": self.wc.id,
                "time_cycle_manual": 5,
            }
        )
        self.env.flush_all()
        mo.action_update_bom()
        self.env.flush_all()
        mo.invalidate_recordset()
        self.assertEqual(
            mo.workorder_ids.mapped("name")[0],
            "Prep",
            "an operation whose routing sequence is 1 did not sort first",
        )

    def test_a_derived_state_cannot_be_set_by_hand(self):
        """`blocked` is derived, so `set_state` refuses it.

        Making a manual `blocked` survive instead would mean giving `state` an
        override escape from its own compute; refusing it keeps one owner for
        the value.  What is not an option is the third behaviour, which is what
        the list dropdown used to offer: accept the write and silently undo it
        on the next change to any input of the ready quantity.
        """
        mo = self._mo(tag="B")
        wo = mo.workorder_ids
        with self.assertRaises(UserError):
            wo.set_state("blocked")
        # `ready` is still settable: for a cancelled work order it is the release.
        wo.action_cancel()
        self.env.flush_all()
        self.assertEqual(wo.state, "cancel")
        wo.set_state("ready")
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.state, "ready")

    def test_writing_both_dates_moves_the_workorder(self):
        """Writing both dates means move, not resize.

        `mrp_workorder.TestWorkOrderProcess.test_planning_8` writes both dates
        to move a work order out of a midday break and asserts its duration
        survives, so the end handed in is discarded on purpose.  Pinned here
        with the escape hatch that makes an exact span expressible, which is
        the part that was missing rather than wrong.
        """
        mo = self._mo(tag="X")
        wo = mo.workorder_ids
        wo.write({"date_start": datetime(2026, 9, 1, 8, 0), "duration_expected": 60})
        self.env.flush_all()
        wo.invalidate_recordset()
        duration = wo.duration_expected

        # Both dates => move: the duration is preserved, the end re-derived.
        wo.write(
            {
                "date_start": datetime(2026, 9, 2, 9, 0),
                "date_end": datetime(2026, 9, 2, 18, 0),
            }
        )
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.date_start, datetime(2026, 9, 2, 9, 0))
        self.assertEqual(wo.duration_expected, duration, "a move must keep the length")
        self.assertNotEqual(wo.date_end, datetime(2026, 9, 2, 18, 0))

        # Passing duration_expected alongside them sets the span verbatim.
        wo.write(
            {
                "date_start": datetime(2026, 9, 3, 8, 0),
                "date_end": datetime(2026, 9, 3, 17, 0),
                "duration_expected": 540,
            }
        )
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.date_end, datetime(2026, 9, 3, 17, 0))
        self.assertEqual(wo.duration_expected, 540)

    def test_starting_a_workorder_does_not_book_a_whole_day(self):
        mo = self._mo(tag="Y")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        wo.invalidate_recordset()
        span = (wo.date_end - wo.date_start).total_seconds() / 60
        self.assertLess(
            span,
            wo.duration_expected * 3,
            "starting a 50-minute job booked the work center for %.1f minutes" % span,
        )

    def test_a_double_booked_workorder_is_never_silent(self):
        """A work order planned onto an occupied slot must say so.

        Not that the popover and the planner give the *same* answer: making
        them agree would mean deleting `_get_conflicted_workorder_ids` and
        flipping a semantics `mrp_workorder` pins deliberately ("Shouldn't have
        a conflict because wo1 is in progress"), which is a product decision.
        What is pinned here is narrower: a work order double-booked onto a
        running one's slot -- a slot `_get_first_available_slot` refuses
        outright -- must not be silent, and it was.
        """
        mo_a = self._mo(tag="CA")
        mo_a.button_plan()
        self.env.flush_all()
        a = mo_a.workorder_ids
        a.button_start()
        self.env.flush_all()
        mo_b = self._mo(tag="CB")
        b = mo_b.workorder_ids
        b.workcenter_id = a.workcenter_id
        b.with_context(bypass_duration_calculation=True).write(
            {"date_start": a.date_start, "date_end": a.date_end}
        )
        self.env.flush_all()
        self.env.invalidate_all()
        planner_start, _stop = a.workcenter_id._get_first_available_slot(
            a.date_start, b.duration_expected
        )
        self.assertGreater(
            planner_start, a.date_start, "the planner should refuse the taken slot"
        )
        self.assertTrue(
            b.show_json_popover,
            "the planner refuses the slot but the popover reports nothing",
        )
        self.assertIn("already booked", b.json_popover)
