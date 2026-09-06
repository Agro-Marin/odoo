from unittest.mock import patch

from dateutil.relativedelta import relativedelta

import odoo.modules.module as odoo_module
from odoo import api
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Date, Datetime
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "data_recycle")
class TestDataRecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.server_model = cls.env["ir.model"]._get("fetchmail.server")

        cls.recycle_model = cls.env["data_recycle.model"].create(
            {
                "name": "Recycle Test Server",
                "res_model_id": cls.server_model.id,
                "domain": "[('date', '<=', 'now -1y')]",
                "recycle_action": "archive",
            }
        )

        cls.old_servers = cls.env["fetchmail.server"].create(
            [
                {
                    "name": "Old Server %s" % (i),
                    "date": Date.today() - relativedelta(years=2),
                }
                for i in range(5)
            ]
        )

        cls.new_servers = cls.env["fetchmail.server"].create(
            [
                {
                    "name": "New Server %s" % (i),
                    "date": Date.today(),
                }
                for i in range(5)
            ]
        )

    def test_recycle_flow(self):
        # Test candidate search
        self.recycle_model._recycle_records()

        self.assertEqual(len(self.recycle_model.recycle_record_ids), 5)
        self.assertEqual(
            set(self.recycle_model.recycle_record_ids.mapped("res_id")),
            set(self.old_servers.ids),
        )

        # Test record deletion outside of the recycle scope
        self.old_servers[0].unlink()
        self.assertEqual(
            self.recycle_model.recycle_record_ids[0].name, "**Record Deleted**"
        )

    def test_recycle_domain(self):
        self.recycle_model.domain = (
            "[('date', '<=', 'now -1y'), ('name', 'not ilike', '0')]"
        )
        self.recycle_model._recycle_records()

        self.assertEqual(len(self.recycle_model.recycle_record_ids), 4)
        self.assertTrue(
            self.old_servers[0].id
            not in self.recycle_model.recycle_record_ids.mapped("res_id")
        )

    def test_recycle_notification(self):
        self.env.ref("base.user_admin").write(
            {
                "email": "mitchell.admin@example.com",
            }
        )
        self.recycle_model.notify_user_ids = [(4, self.env.ref("base.user_admin").id)]
        old_notif_count = self.env["mail.notification"].search_count([])
        self.recycle_model._cron_recycle_records()
        new_notif_count = self.env["mail.notification"].search_count([])
        self.assertEqual(new_notif_count, old_notif_count + 1)

    def test_recycle_archive(self):
        self.recycle_model._recycle_records()
        self.recycle_model.recycle_record_ids.action_validate()
        self.assertFalse(self.recycle_model.recycle_record_ids.exists())
        self.assertTrue(all(not p.active for p in self.old_servers))

    def test_recycle_unlink(self):
        self.recycle_model.recycle_action = "unlink"
        self.recycle_model._recycle_records()
        self.recycle_model.recycle_record_ids.action_validate()
        self.assertFalse(self.recycle_model.recycle_record_ids.exists())
        self.assertFalse(self.old_servers.exists())

    def test_include_archived(self):
        self.recycle_model.recycle_action = "unlink"
        self.old_servers[0].active = False
        self.recycle_model._recycle_records()
        self.assertEqual(len(self.recycle_model.recycle_record_ids), 4)
        self.recycle_model.include_archived = True
        self.recycle_model._recycle_records()
        self.assertEqual(len(self.recycle_model.recycle_record_ids), 5)

    def test_include_archived_is_ignored_when_archiving(self):
        """An already archived record has nothing left for the archive action to do."""
        self.old_servers[0].active = False
        self.recycle_model.include_archived = True
        self.recycle_model._recycle_records()
        self.assertEqual(
            set(self.recycle_model.recycle_record_ids.mapped("res_id")),
            set(self.old_servers[1:].ids),
            "the field is hidden for the archive action, so it must not act there either",
        )

    # Queue reconciliation

    def test_a_tightened_rule_drops_the_records_it_no_longer_selects(self):
        self.recycle_model._recycle_records()
        self.assertEqual(len(self.recycle_model.recycle_record_ids), 5)

        self.recycle_model.domain = "[('name', '=', 'Old Server 0')]"
        self.recycle_model._recycle_records()
        self.assertEqual(
            self.recycle_model.recycle_record_ids.mapped("res_id"),
            self.old_servers[0].ids,
            "records the rule stopped selecting must not stay queued for recycling",
        )

    def test_changing_the_model_does_not_retarget_the_queue(self):
        """The res_ids of one table are meaningless in another."""
        self.recycle_model._recycle_records()
        self.assertTrue(self.recycle_model.recycle_record_ids)
        queued_res_ids = set(self.recycle_model.recycle_record_ids.mapped("res_id"))

        self.recycle_model.write(
            {
                "res_model_id": self.env["ir.model"]._get("res.partner").id,
                "domain": "[('name', '=', 'a name no partner has')]",
            }
        )
        self.recycle_model._recycle_records()
        self.assertFalse(
            self.recycle_model.recycle_record_ids,
            "the fetchmail ids %s would have been archived as partners"
            % sorted(queued_res_ids),
        )

    def test_changing_the_model_empties_the_queue_at_once(self):
        """Not only on the next run: in between, the queue reads as work to do."""
        self.recycle_model._recycle_records()
        self.assertTrue(self.recycle_model.recycle_record_ids)

        self.recycle_model.res_model_id = self.env["ir.model"]._get("res.partner")
        self.assertFalse(
            self.env["data_recycle.record"]
            .with_context(active_test=False)
            .search([("recycle_model_id", "=", self.recycle_model.id)])
        )

    def test_rewriting_the_same_model_keeps_the_queue(self):
        self.recycle_model._recycle_records()
        before = self.recycle_model.recycle_record_ids
        self.assertTrue(before)
        self.recycle_model.write(
            {"name": "renamed", "res_model_id": self.server_model.id}
        )
        self.assertEqual(self.recycle_model.recycle_record_ids, before)

    def test_a_deleted_record_leaves_the_queue_on_the_next_run(self):
        self.recycle_model._recycle_records()
        self.old_servers[0].unlink()
        self.recycle_model._recycle_records()
        self.assertEqual(len(self.recycle_model.recycle_record_ids), 4)
        self.assertNotIn(
            "**Record Deleted**", self.recycle_model.recycle_record_ids.mapped("name")
        )

    def test_a_stale_only_pass_survives_a_later_rules_crash(self):
        """A rule's own reconciled stale-delete must not be lost to a crash in
        a DIFFERENT, later rule of the same cron pass -- and the transaction
        rollback that follows it -- when this rule itself proposed no new
        candidates and so never took the batch-loop's own commit."""
        self.recycle_model._recycle_records()
        stale_res_id = self.old_servers[0].id
        self.old_servers[0].unlink()

        crashing_rule = self.env["data_recycle.model"].create(
            {
                "name": "ZZZ Crashes",
                "res_model_id": self.server_model.id,
                "recycle_action": "unlink",
                "domain": "[('id', '>', 0)]",
            }
        )

        Model = type(self.recycle_model)
        original_recycle_records = Model._recycle_records

        def crash_for_the_crashing_rule(model_self, batch_commits=False):
            if model_self.id == crashing_rule.id:
                raise ZeroDivisionError("forced failure for this test")
            return original_recycle_records(model_self, batch_commits=batch_commits)

        self.env.flush_all()
        # `_cron_recycle_records` only takes its commit/rollback branches
        # outside of a test run, and a `TransactionCase` cursor forbids both
        # outright -- so exercise them on a real, registry-test-mode cursor
        # with that guard patched off, the same way core's own `ir.cron`
        # tests do for code that commits mid-run. The cursor must be opened
        # while `current_test` is still set -- `TestCursor` itself asserts
        # that on open -- so the patch only wraps the call, not the `with`.
        with self.enter_registry_test_mode(), self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self.env.context)
            with (
                patch.object(odoo_module, "current_test", False),
                patch.object(Model, "_recycle_records", crash_for_the_crashing_rule),
            ):
                env["data_recycle.model"].search([])._cron_recycle_records()

        self.recycle_model.invalidate_recordset()
        self.assertNotIn(
            stale_res_id,
            self.recycle_model.recycle_record_ids.mapped("res_id"),
            "the crashing rule's failure must not roll back this rule's own, "
            "already-decided stale-record cleanup",
        )

    def test_a_discarded_record_is_not_proposed_again(self):
        self.recycle_model._recycle_records()
        discarded = self.recycle_model.recycle_record_ids[0]
        discarded.action_discard()
        self.recycle_model._recycle_records()
        self.assertFalse(discarded.active)
        self.assertEqual(
            len(self.recycle_model.with_context(active_test=False).recycle_record_ids),
            5,
        )

    def test_archiving_the_rule_clears_discarded_records_too(self):
        self.recycle_model._recycle_records()
        self.recycle_model.recycle_record_ids[0].action_discard()
        self.recycle_model.active = False
        self.assertFalse(
            self.env["data_recycle.record"]
            .with_context(active_test=False)
            .search([("recycle_model_id", "=", self.recycle_model.id)]),
            "a discarded record must not outlive the rule that produced it",
        )

    # Guards

    def test_a_rule_with_no_filter_refuses_to_run(self):
        unfiltered = self.env["data_recycle.model"].create(
            {
                "name": "Everything",
                "res_model_id": self.server_model.id,
                "recycle_action": "archive",
            }
        )
        with self.assertRaises(UserError):
            unfiltered._recycle_records()
        self.assertFalse(unfiltered.recycle_record_ids)

        # `[(1, '=', 1)]` parses to the same domain as `[]`, so it is refused too.
        unfiltered.domain = "[(1, '=', 1)]"
        with self.assertRaises(UserError):
            unfiltered._recycle_records()

    def test_every_record_can_still_be_targeted_on_purpose(self):
        """The guard must leave a way through, and its message names this one."""
        everything = self.env["data_recycle.model"].create(
            {
                "name": "Everything, deliberately",
                "res_model_id": self.server_model.id,
                "recycle_action": "archive",
                "domain": "[('id', '>', 0)]",
            }
        )
        everything._recycle_records()
        self.assertEqual(
            len(everything.recycle_record_ids),
            len(self.old_servers) + len(self.new_servers),
        )

    def test_an_age_condition_is_expressed_in_the_filter(self):
        """`now -Ny` on a Datetime, `today -Ny` on a Date: what replaced the triple."""
        self.assertEqual(
            set(self.recycle_model.recycle_record_ids.mapped("res_id")), set()
        )
        self.recycle_model._recycle_records()
        self.assertEqual(
            set(self.recycle_model.recycle_record_ids.mapped("res_id")),
            set(self.old_servers.ids),
            "the two-year-old servers, and only those",
        )

        self.recycle_model.domain = "[('date', '<=', 'now -3y')]"
        self.recycle_model._recycle_records()
        self.assertFalse(
            self.recycle_model.recycle_record_ids, "nothing is three years old"
        )

    def test_an_invalid_filter_is_refused_at_save_time(self):
        with self.assertRaises(ValidationError):
            self.recycle_model.domain = "[('no_such_field', '=', 1)]"
        with self.assertRaises(ValidationError):
            self.recycle_model.domain = "[('name', '=', context_today())]"

    def test_archive_needs_a_model_that_can_be_archived(self):
        with self.assertRaises(ValidationError):
            self.recycle_model.res_model_id = self.env["ir.model"]._get("ir.model.data")

    def test_a_rule_targeting_an_uninstalled_model_does_not_crash_the_cron(self):
        ghost = self.env["ir.model"].create(
            {"name": "Ghost", "model": "x_data_recycle.ghost"}
        )
        self.env["data_recycle.model"].create(
            {
                "name": "Ghost rule",
                "res_model_id": ghost.id,
                "recycle_action": "unlink",
                "domain": "[('id', '>', 0)]",
            }
        )
        self.env.registry.models.pop("x_data_recycle.ghost", None)
        self.env["data_recycle.model"]._cron_recycle_records()
        self.assertTrue(
            self.recycle_model.recycle_record_ids,
            "the healthy rule must still have run",
        )

    def test_action_recycle_records_is_single_record(self):
        self.recycle_model.copy({"name": "Second rule"})
        rules = self.env["data_recycle.model"].search([])
        self.assertGreater(len(rules), 1)
        with self.assertRaises(ValueError):
            rules.action_recycle_records()

    # Validation robustness

    def test_one_undeletable_record_does_not_cost_the_others(self):
        countries = self.env["res.country"].search([("code", "in", ["BE", "LU", "MC"])])
        self.assertEqual(len(countries), 3)
        pinned = self.env.ref("base.be")
        recyclable = countries - pinned
        self.env["res.partner"].create(
            {"name": "Pins Belgium", "country_id": pinned.id}
        )

        rule = self.env["data_recycle.model"].create(
            {
                "name": "Countries",
                "recycle_action": "unlink",
                "res_model_id": self.env["ir.model"]._get("res.country").id,
                "domain": "[('code', 'in', ['BE', 'LU', 'MC'])]",
            }
        )
        rule._recycle_records()
        self.assertEqual(len(rule.recycle_record_ids), 3)

        rule.recycle_record_ids.action_validate()
        self.assertTrue(pinned.exists(), "the pinned country cannot be deleted")
        self.assertFalse(recyclable.exists(), "the other two must go through")
        self.assertEqual(
            rule.recycle_record_ids.mapped("res_id"),
            pinned.ids,
            "only the record that refused stays queued",
        )

    def test_automatic_mode_survives_a_record_that_refuses(self):
        self.env["res.partner"].create(
            {"name": "Pins Belgium", "country_id": self.env.ref("base.be").id}
        )
        rule = self.env["data_recycle.model"].create(
            {
                "name": "Countries",
                "recycle_action": "unlink",
                "recycle_mode": "automatic",
                "res_model_id": self.env["ir.model"]._get("res.country").id,
                "domain": "[('code', 'in', ['BE', 'LU', 'MC'])]",
            }
        )
        rule._recycle_records()
        self.assertFalse(self.env["res.country"].search([("code", "in", ["LU", "MC"])]))
        self.assertTrue(self.env.ref("base.be").exists())

    def test_automatic_mode_recycles_without_queueing(self):
        self.recycle_model.recycle_mode = "automatic"
        self.recycle_model._recycle_records()
        self.assertFalse(self.recycle_model.recycle_record_ids)
        self.assertFalse(any(server.active for server in self.old_servers))
        self.assertTrue(all(server.active for server in self.new_servers))

    # Notifications

    def test_a_silent_run_does_not_consume_the_notification_period(self):
        self.env.ref("base.user_admin").email = "mitchell.admin@example.com"
        self.recycle_model.notify_user_ids = self.env.ref("base.user_admin")
        self.recycle_model.notify_frequency_period = "weeks"

        self.recycle_model._notify_pending_records()
        self.assertFalse(
            self.recycle_model.last_notification,
            "nothing was sent, so the period must not be consumed",
        )

        self.recycle_model._recycle_records()
        notifications = self.env["mail.notification"].search_count([])
        self.recycle_model._notify_pending_records()
        self.assertEqual(
            self.env["mail.notification"].search_count([]), notifications + 1
        )
        self.assertTrue(self.recycle_model.last_notification)

    def test_the_notification_waits_out_its_period(self):
        self.env.ref("base.user_admin").email = "mitchell.admin@example.com"
        self.recycle_model.notify_user_ids = self.env.ref("base.user_admin")
        self.recycle_model._recycle_records()
        self.recycle_model._notify_pending_records()
        notifications = self.env["mail.notification"].search_count([])

        self.recycle_model._notify_pending_records()
        self.assertEqual(self.env["mail.notification"].search_count([]), notifications)

        self.recycle_model.last_notification = Datetime.now() - relativedelta(weeks=2)
        self.recycle_model._notify_pending_records()
        self.assertEqual(
            self.env["mail.notification"].search_count([]), notifications + 1
        )

    def test_the_notification_counts_the_whole_backlog(self):
        self.env.ref("base.user_admin").email = "mitchell.admin@example.com"
        self.recycle_model.notify_user_ids = self.env.ref("base.user_admin")
        self.recycle_model._recycle_records()
        self.env["data_recycle.record"].search(
            [("recycle_model_id", "=", self.recycle_model.id)]
        ).write({"create_date": Datetime.now() - relativedelta(years=1)})

        self.assertTrue(
            self.recycle_model._send_notification(),
            "a backlog older than the notification period is still a backlog",
        )

    # Queue records

    def test_the_queue_carries_the_company_of_its_records(self):
        company = self.env["res.company"].create({"name": "Recycle Co"})
        partner = self.env["res.partner"].create(
            {"name": "Zizzy", "company_id": company.id}
        )
        rule = self.env["data_recycle.model"].create(
            {
                "name": "Partners",
                "recycle_action": "archive",
                "res_model_id": self.env["ir.model"]._get("res.partner").id,
                "domain": "[('name', '=', 'Zizzy')]",
            }
        )
        rule._recycle_records()
        self.assertEqual(rule.recycle_record_ids.res_id, partner.id)
        self.assertEqual(rule.recycle_record_ids.company_id, company)

    def test_the_queue_survives_a_model_with_no_company(self):
        self.recycle_model._recycle_records()
        self.assertFalse(self.recycle_model.recycle_record_ids.company_id)
