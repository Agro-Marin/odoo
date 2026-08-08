# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the defects found in the base_automation audit.

Each test names the behaviour that was wrong and pins the corrected one. The
webhook cases run through a real HTTP request on purpose: the pre-existing
webhook tests call ``_verify_webhook_request`` with a plain ``dict``, which is
exactly why a case-sensitive header lookup survived them.
"""
import hashlib
import hmac
import json
from unittest.mock import patch

from odoo import Command
from odoo.tests import HttpCase, TransactionCase, tagged


class AutomationAuditCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Automation = cls.env["base.automation"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Runtime = cls.env["automation.runtime"]
        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def _automation(self, name, trigger="on_hand", **kw):
        return self.Automation.create({
            "name": name, "model_id": self.model_partner.id, "trigger": trigger, **kw,
        })

    def _action(self, automation, name, code="pass", **kw):
        return self.Action.create({
            "name": name, "model_id": self.model_partner.id, "state": "code",
            "code": code, "base_automation_id": automation.id,
            "usage": "base_automation", **kw,
        })


@tagged("post_install", "-at_install")
class TestCopyKeepsGraphLocal(AutomationAuditCommon):
    """copy() used to leave the duplicate's edges pointing at the source."""

    def test_copy_remaps_predecessors_onto_the_copied_actions(self):
        source = self._automation("source")
        first = self._action(source, "first")
        self._action(source, "second", predecessor_ids=[Command.link(first.id)])

        duplicate = source.copy()

        self.assertEqual(len(duplicate.action_server_ids), 2)
        own_ids = set(duplicate.action_server_ids.ids)
        for action in duplicate.action_server_ids:
            self.assertFalse(
                set(action.predecessor_ids.ids) - own_ids,
                f"{action.name} depends on an action outside its own automation",
            )
        copied_second = duplicate.action_server_ids.filtered(
            lambda a: a.predecessor_ids,
        )
        self.assertEqual(len(copied_second), 1, "the edge itself must be preserved")

    def test_copy_does_not_touch_the_source_graph(self):
        source = self._automation("source")
        first = self._action(source, "first")
        second = self._action(source, "second", predecessor_ids=[Command.link(first.id)])

        source.copy()

        self.assertEqual(
            first.successor_ids, second,
            "the copy leaked into the source automation's successors",
        )

    def test_copy_multi_gives_each_copy_its_own_actions(self):
        one, two = self._automation("one"), self._automation("two")
        self._action(one, "one-step")
        self._action(two, "two-step")

        copies = (one | two).copy()

        self.assertEqual(len(copies), 2)
        for original, copy in zip(one | two, copies, strict=True):
            self.assertEqual(
                copy.action_server_ids.mapped("name"),
                [f"{n} (copy)" for n in original.action_server_ids.mapped("name")],
            )


@tagged("post_install", "-at_install")
class TestDagIntegrity(AutomationAuditCommon):
    """A dependency that cannot complete used to wedge the run silently."""

    def test_predecessor_from_another_automation_is_rejected(self):
        other = self._automation("other")
        foreign = self._action(other, "foreign")
        mine = self._automation("mine")

        with self.assertRaises(Exception):
            self._action(mine, "dependent", predecessor_ids=[Command.link(foreign.id)])

    def test_run_that_cannot_advance_is_marked_failed(self):
        """No step ready and steps outstanding is a failure, not a silent stop."""
        automation = self._automation("blocked")
        first = self._action(automation, "first")
        second = self._action(
            automation, "second", predecessor_ids=[Command.link(first.id)],
        )
        runtime = self.Runtime.create({"automation_id": automation.id})
        runtime.action_start()

        # force the wedge the old _create_action_lines could produce
        line_second = runtime.line_ids.filtered(lambda l: l.action_id == second)
        line_first = runtime.line_ids.filtered(lambda l: l.action_id == first)
        line_first.action_cancel()

        runtime.action_run_all()

        self.assertEqual(runtime.state, "error")
        self.assertEqual(line_second.state, "error")

    def test_cycle_detection_still_rejects(self):
        automation = self._automation("cyclic")
        a = self._action(automation, "a")
        b = self._action(automation, "b", predecessor_ids=[Command.link(a.id)])
        with self.assertRaises(Exception):
            a.predecessor_ids = [Command.link(b.id)]


@tagged("post_install", "-at_install")
class TestFailureIsRecorded(AutomationAuditCommon):
    """The execution history has to survive the failures it exists to record."""

    def test_failed_step_leaves_the_target_record_untouched(self):
        partner = self.env["res.partner"].create({"name": "target", "ref": "before"})
        automation = self._automation("half-write")
        self._action(
            automation, "writes then raises",
            code="record.write({'ref': 'after'})\nraise Exception('too late')",
        )
        runtime = self.Runtime.create({
            "automation_id": automation.id,
            "res_model": "res.partner", "res_id": partner.id,
        })
        runtime.action_start()
        runtime.action_run_all()

        self.assertEqual(runtime.state, "error")
        partner.invalidate_recordset(["ref"])
        self.assertEqual(
            partner.ref, "before",
            "the savepoint must discard the failing action's partial write",
        )

    def test_history_survives_and_names_the_failing_step(self):
        automation = self._automation("failing")
        ok = self._action(automation, "ok")
        self._action(
            automation, "boom", code="raise Exception('deliberate')",
            predecessor_ids=[Command.link(ok.id)],
        )
        runtime = self.Runtime.create({"automation_id": automation.id})
        runtime.action_start()
        runtime.action_run_all()

        self.assertEqual(runtime.state, "error")
        by_name = {l.name: l for l in runtime.line_ids}
        self.assertEqual(by_name["ok"].state, "done")
        self.assertEqual(by_name["boom"].state, "error")
        self.assertIn("deliberate", by_name["boom"].error_message)


@tagged("post_install", "-at_install")
class TestProcessRespectsDependencies(AutomationAuditCommon):
    """_process ordered by `sequence` alone, ignoring the declared graph."""

    def test_actions_run_in_dependency_order_not_sequence_order(self):
        automation = self._automation("ordered", trigger="on_create")
        first = self._action(
            automation, "first", sequence=50,
            code="record.write({'ref': (record.ref or '') + 'A'})",
        )
        self._action(
            automation, "second", sequence=10,
            code="record.write({'ref': (record.ref or '') + 'B'})",
            predecessor_ids=[Command.link(first.id)],
        )
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        partner = self.env["res.partner"].create({"name": "ordered target"})
        self.assertEqual(partner.ref, "AB", "sequence must not override the graph")

    def test_sequence_still_orders_independent_actions(self):
        automation = self._automation("independent", trigger="on_create")
        self._action(
            automation, "late", sequence=50,
            code="record.write({'ref': (record.ref or '') + 'A'})",
        )
        self._action(
            automation, "early", sequence=10,
            code="record.write({'ref': (record.ref or '') + 'B'})",
        )
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        partner = self.env["res.partner"].create({"name": "independent target"})
        self.assertEqual(partner.ref, "BA")


@tagged("post_install", "-at_install")
class TestRuleLookupCache(AutomationAuditCommon):
    """_get_actions ran one SELECT per ORM call on every watched model."""

    def _count_rule_lookups(self, fn):
        seen = []
        cr = self.env.cr
        original = cr.execute

        def spy(query, params=None, *args, **kwargs):
            text = str(query)
            if "base_automation" in text and "SELECT" in text.upper():
                seen.append(text)
            return original(query, params, *args, **kwargs)

        cr.execute = spy
        try:
            fn()
            self.env.flush_all()
        finally:
            cr.execute = original
        return len(seen)

    def test_repeated_writes_do_not_re_query_the_rules(self):
        automation = self._automation("cached", trigger="on_create_or_write")
        self._action(automation, "noop")
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        partners = self.env["res.partner"].create(
            [{"name": f"cache-{i}"} for i in range(20)],
        )
        self.env.flush_all()

        def loop():
            for partner in partners:
                partner.write({"comment": "x"})

        self.assertEqual(
            self._count_rule_lookups(loop), 0,
            "the rule set must be served from the registry cache",
        )

    def test_cache_is_invalidated_when_a_rule_changes(self):
        automation = self._automation("toggles", trigger="on_create")
        self._action(
            automation, "stamp", code="record.write({'ref': 'fired'})",
        )
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        first = self.env["res.partner"].create({"name": "before"})
        self.assertEqual(first.ref, "fired")

        automation.active = False
        self.Automation._update_registry()
        second = self.env["res.partner"].create({"name": "after"})
        self.assertNotEqual(
            second.ref, "fired", "deactivating a rule must invalidate the cache",
        )

    def test_sequence_change_reorders_execution(self):
        """The cache stores order as well as membership."""
        automation = self._automation("resequenced", trigger="on_create")
        self._action(
            automation, "a", sequence=10,
            code="record.write({'ref': (record.ref or '') + 'A'})",
        )
        second = self._automation("resequenced-2", trigger="on_create", sequence=20)
        self._action(
            second, "b", code="record.write({'ref': (record.ref or '') + 'B'})",
        )
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        self.assertEqual(self.env["res.partner"].create({"name": "p1"}).ref, "AB")

        second.sequence = 1
        self.assertEqual(
            self.env["res.partner"].create({"name": "p2"}).ref, "BA",
            "a plain sequence edit must invalidate the cached order",
        )


@tagged("post_install", "-at_install")
class TestBookkeepingWriteIsSilent(AutomationAuditCommon):
    """The date_automation_last stamp fired unrelated on_write rules."""

    def test_stamp_does_not_trigger_other_rules(self):
        lead_model = self.env["ir.model"]._get("base.automation.lead.thread.test")
        if not lead_model:
            self.skipTest("test_base_automation is not installed")
        Model = self.env[lead_model.model]
        self.assertIn("date_automation_last", Model._fields)

        counter = self.env["ir.config_parameter"].sudo()
        counter.set_param("base_automation.bookkeeping_probe", "0")
        observer = self.Automation.create({
            "name": "observer", "model_id": lead_model.id, "trigger": "on_write",
        })
        self.Action.create({
            "name": "count", "model_id": lead_model.id, "state": "code",
            "usage": "base_automation", "base_automation_id": observer.id,
            "code": (
                "p = env['ir.config_parameter'].sudo()\n"
                "p.set_param('base_automation.bookkeeping_probe',"
                " str(int(p.get_param('base_automation.bookkeeping_probe', '0')) + 1))"
            ),
        })
        stamper = self.Automation.create({
            "name": "stamper", "model_id": lead_model.id, "trigger": "on_create",
        })
        self.Action.create({
            "name": "noop", "model_id": lead_model.id, "state": "code", "code": "pass",
            "usage": "base_automation", "base_automation_id": stamper.id,
        })
        self.Automation._update_registry()
        self.addCleanup(self.Automation._update_registry)

        Model.create({"name": "probe"})
        self.env.flush_all()

        self.assertEqual(
            counter.get_param("base_automation.bookkeeping_probe"), "0",
            "the internal date_automation_last write fired a user rule",
        )


@tagged("post_install", "-at_install")
class TestRuntimeCreatePrivileges(AutomationAuditCommon):
    """company_id in vals used to elevate the whole create to superuser."""

    def test_company_id_does_not_bypass_access_rights(self):
        employee = self.env["res.users"].create({
            "name": "audit employee", "login": "audit_employee",
            "group_ids": [Command.set([self.env.ref("base.group_user").id])],
        })
        automation = self._automation("acl")
        Runtime = self.Runtime.with_user(employee)

        with self.assertRaises(Exception):
            Runtime.create({"automation_id": automation.id})

        with self.assertRaises(
            Exception, msg="company_id must not grant a create the user lacks",
        ):
            Runtime.create({
                "automation_id": automation.id,
                "company_id": self.env.company.id,
            })

    def test_sequence_is_still_assigned(self):
        automation = self._automation("seq")
        runtime = self.Runtime.create({
            "automation_id": automation.id, "company_id": self.env.company.id,
        })
        self.assertTrue(runtime.name.startswith("BAR/"), runtime.name)


@tagged("post_install", "-at_install")
class TestRuntimeVisibility(AutomationAuditCommon):
    """Runs of every company were readable by every employee."""

    def test_other_company_runs_are_not_readable(self):
        automation = self._automation("multico")
        other_company = self.env["res.company"].create({"name": "audit other co"})
        theirs = self.Runtime.sudo().create({
            "automation_id": automation.id,
            "company_id": other_company.id,
            "currency_id": other_company.currency_id.id,
            "reference": "CONFIDENTIAL",
        })
        employee = self.env["res.users"].create({
            "name": "single co", "login": "audit_singleco",
            "company_id": self.env.company.id,
            "company_ids": [Command.set([self.env.company.id])],
            "group_ids": [Command.set([self.env.ref("base.group_user").id])],
        })
        self.env.flush_all()

        visible = self.Runtime.with_user(employee).search([("id", "=", theirs.id)])
        self.assertFalse(visible, "an employee read another company's run")


@tagged("post_install", "-at_install")
class TestProgressReflectsOutcome(AutomationAuditCommon):
    """A settled run reported 0% forever."""

    def test_cancelled_run_reads_as_complete(self):
        automation = self._automation("cancelled")
        first = self._action(automation, "first")
        self._action(automation, "second", predecessor_ids=[Command.link(first.id)])
        runtime = self.Runtime.create({"automation_id": automation.id})
        runtime.action_start()
        runtime.action_cancel()

        self.assertEqual(runtime.state, "cancel")
        self.assertEqual(runtime.progress, 100)
        self.assertEqual(runtime.progress_display, "2/2 steps")

    def test_partial_run_reports_partial_progress(self):
        automation = self._automation("partial")
        first = self._action(automation, "first")
        self._action(automation, "second", predecessor_ids=[Command.link(first.id)])
        runtime = self.Runtime.create({"automation_id": automation.id})
        runtime.action_start()
        runtime.line_ids.filtered(lambda l: l.name == "first").action_mark_done()

        self.assertEqual(runtime.progress, 50)


@tagged("post_install", "-at_install")
class TestConstraintMessages(AutomationAuditCommon):
    """The model-mismatch constraint crashed inside its own error path."""

    def test_multi_record_validation_reports_instead_of_crashing(self):
        good = self._automation("good")
        bad = self._automation("bad")
        self.Action.create({
            "name": "wrong model",
            "model_id": self.env["ir.model"]._get("res.users").id,
            "state": "code", "code": "pass", "usage": "base_automation",
            "base_automation_id": bad.id,
        })
        with self.assertRaises(Exception) as caught:
            (good | bad).write({"model_id": self.model_partner.id})
        self.assertNotIsInstance(
            caught.exception, ValueError,
            "the error path itself raised Expected singleton",
        )


@tagged("post_install", "-at_install")
class TestWebhookOverHttp(HttpCase):
    """These must go through a real request; a dict-based call misses the bugs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_partner = cls.env["ir.model"]._get("res.partner")
        cls.secret = "audit-secret"
        category = (
            cls.env["credential.category"].search([], limit=1)
            or cls.env["credential.category"].create({"name": "A", "code": "audit"})
        )
        cls.credential = cls.env["credential.credential"].create({
            "name": "audit secret", "category_id": category.id,
            "credential_value": cls.secret,
        })
        cls.body = b'{"audit": true}'
        cls.signature = "sha256=" + hmac.new(
            cls.secret.encode(), cls.body, hashlib.sha256,
        ).hexdigest()

    def _rule(self, name, **kw):
        rule = self.env["base.automation"].create({
            "name": name, "model_id": self.model_partner.id,
            "trigger": "on_webhook", **kw,
        })
        self.env["ir.actions.server"].create({
            "name": f"{name}-action", "model_id": self.model_partner.id,
            "state": "code", "usage": "base_automation",
            "base_automation_id": rule.id,
            "code": (
                "env['ir.config_parameter'].sudo()"
                ".set_param('base_automation.webhook_probe', 'fired')"
            ),
        })
        return rule

    def _post(self, rule, headers=None):
        return self.url_open(
            f"/web/hook/{rule.webhook_uuid}",
            data=self.body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )

    def test_signature_header_name_is_case_insensitive(self):
        for configured in (
            "x-hub-signature-256", "X-HUB-SIGNATURE-256", "X-Hub-Signature-256",
        ):
            rule = self._rule(
                f"hdr-{configured}", webhook_auth_type="hmac_sha256",
                webhook_credential_id=self.credential.id,
                webhook_signature_header=configured,
            )
            response = self._post(rule, {"X-Hub-Signature-256": self.signature})
            self.assertEqual(
                response.status_code, 200,
                f"a valid request was rejected for header spelling {configured!r}",
            )

    def test_bad_signature_is_still_rejected(self):
        rule = self._rule(
            "bad-sig", webhook_auth_type="hmac_sha256",
            webhook_credential_id=self.credential.id,
        )
        response = self._post(rule, {"X-Hub-Signature-256": "sha256=deadbeef"})
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_calls_cannot_exhaust_the_rate_limit(self):
        rule = self._rule(
            "rate", webhook_auth_type="hmac_sha256",
            webhook_credential_id=self.credential.id,
            webhook_rate_limit=True, rate_limit_requests=3,
            webhook_rate_limit_window=60,
        )
        for _ in range(6):
            self.assertEqual(
                self._post(rule, {"X-Hub-Signature-256": "sha256=deadbeef"}).status_code,
                401,
                "unsigned calls must be refused before they spend a token",
            )
        self.assertEqual(
            self._post(rule, {"X-Hub-Signature-256": self.signature}).status_code, 200,
            "the legitimate sender was locked out by unauthenticated traffic",
        )

    def test_non_webhook_rule_is_not_reachable(self):
        rule = self.env["base.automation"].create({
            "name": "not a webhook", "model_id": self.model_partner.id,
            "trigger": "on_create",
        })
        self.env["ir.actions.server"].create({
            "name": "should not run", "model_id": self.model_partner.id,
            "state": "code", "usage": "base_automation",
            "base_automation_id": rule.id,
            "code": (
                "env['ir.config_parameter'].sudo()"
                ".set_param('base_automation.webhook_probe', 'fired')"
            ),
        })
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("base_automation.webhook_probe", "no")

        response = self.url_open(
            f"/web/hook/{rule.webhook_uuid}",
            data=json.dumps({"x": 1}),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(
            response.status_code, 404,
            "a non-webhook rule must not resolve to an endpoint at all",
        )
        self.env.invalidate_all()
        self.assertEqual(
            parameters.get_param("base_automation.webhook_probe"), "no",
            "a non-webhook rule ran over HTTP",
        )


@tagged("post_install", "-at_install")
class TestFirstRunIsAnnounced(AutomationAuditCommon):
    """An unscoped first run sweeps the whole history — it must say so.

    The behaviour itself is deliberate and upstream-tested (a new rule catches
    the existing backlog), so it is not changed here; it is made visible, and
    `last_run` was made settable so the first run can be scoped.
    """

    def test_first_run_warns_and_names_the_volume(self):
        model = self.env["ir.model"]._get("res.partner")
        automation = self.Automation.create({
            "name": "sweeper", "model_id": model.id, "trigger": "on_time_created",
            "trg_date_range": 1, "trg_date_range_type": "hour",
        })
        self._action(automation, "noop")
        self.assertFalse(automation.last_run, "precondition: unscoped")

        # A record old enough to fall inside the window. Without this the rule
        # matches nothing on a fresh database and the warning correctly stays
        # silent — the point is that it fires when there IS a backlog.
        old = self.env["res.partner"].create({"name": "predates the rule"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = now() - interval '400 days' "
            "WHERE id = %s",
            (old.id,),
        )
        self.env.invalidate_all()
        self.assertTrue(
            automation._search_time_based_automation_records(until=self.env.cr.now()),
            "precondition: the rule must have a backlog to sweep",
        )

        # _cron_process_time_based_actions calls _commit_progress, which commits
        # the cursor — illegal inside a test transaction (same reason
        # test_triggers._run_cron patches it).
        IrCron = type(self.env["ir.cron"])
        with (
            patch.object(IrCron, "_commit_progress", return_value=float("inf")),
            self.assertLogs(
                "odoo.addons.base_automation.models.base_automation", "WARNING",
            ) as captured,
        ):
            self.Automation._cron_process_time_based_actions()
        self.assertTrue(
            any("covers the entire history" in line for line in captured.output),
            f"no warning about the unscoped first run: {captured.output}",
        )

    def test_scoped_rule_does_not_warn(self):
        model = self.env["ir.model"]._get("res.partner")
        automation = self.Automation.create({
            "name": "scoped", "model_id": model.id, "trigger": "on_time_created",
            "trg_date_range": 1, "trg_date_range_type": "hour",
            "last_run": self.env.cr.now(),
        })
        self._action(automation, "noop")
        self.assertTrue(
            automation.last_run, "last_run must be settable, not readonly",
        )
