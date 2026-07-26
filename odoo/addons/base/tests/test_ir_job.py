"""Tests of the framework job queue (``ir.job``).

Everything runs on the test cursor: ``_claim_next`` / ``_run_claimed`` /
``_record_failure`` / ``_reap_dead_jobs`` all take an explicit ``cr`` so the
whole claim/execute/finalize state machine is exercised inside the test
transaction, without workers or extra connections.
"""

from datetime import timedelta
from unittest.mock import patch

import odoo
from odoo import api, fields
from odoo.exceptions import RetryableJobError, UserError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_job import IrJob


@api.job(channel="root", priority=7, max_retries=2)
def _ir_job_test_append(self, suffix="!"):
    for record in self:
        record.name = record.name + suffix


@api.job
def _ir_job_test_boom(self, retryable=False, seconds=None):
    if retryable:
        raise RetryableJobError("try me later", seconds=seconds)
    raise ValueError("boom")


def _isolate_queue(env):
    """Hide the database's own queue state from the claim assertions.

    ``_claim_next`` looks at the whole *database*, so these tests only hold on a
    database whose queue is empty and unconfigured -- which a restored dump, a
    developer's ``_job_ping`` or a deployment that simply raised the ``root``
    channel's capacity is not.  Two independent kinds of state leak in:

    * queued ``ir.job`` rows -- ``_claim`` returns someone else's job and the
      assertions read the wrong row;
    * ``ir.job.channel`` rows -- the capacity assertions assume the *implicit*
      capacity of 1 for an unconfigured channel, so a configured ``root`` makes
      them claim more than they expect.

    Both are neutralised inside the test transaction and roll back with it, so
    the real queue and its configuration are untouched.
    """
    env.cr.execute(
        "UPDATE ir_job SET state = 'cancelled'"
        " WHERE state IN ('wait_deps', 'pending', 'started')"
    )
    env.cr.execute("DELETE FROM ir_job_channel")


class TestIrJob(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_cls = type(cls.env["res.partner"])
        for func in (_ir_job_test_append, _ir_job_test_boom):
            setattr(cls.partner_cls, func.__name__, func)
            cls.addClassCleanup(delattr, cls.partner_cls, func.__name__)
        cls.partner = cls.env["res.partner"].create({"name": "job target"})
        _isolate_queue(cls.env)

    def _claim(self):
        return IrJob._claim_next(self.env.cr, "test:0")

    def test_delayed_enqueues_pending_job(self):
        job = self.partner.delayed()._ir_job_test_append("?")
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.model_name, "res.partner")
        self.assertEqual(job.method_name, "_ir_job_test_append")
        self.assertEqual(job.record_ids, self.partner.ids)
        self.assertEqual(job.args, ["?"])
        self.assertEqual(job.kwargs, {})
        self.assertEqual(job.channel, "root")
        self.assertEqual(job.priority, 7)
        self.assertEqual(job.max_retries, 2)
        self.assertEqual(job.user_id.id, self.env.uid)
        self.assertTrue(job.uuid)
        self.assertFalse(job.eta)

    def test_delayed_overrides_decorator_defaults(self):
        job = self.partner.delayed(
            priority=1, channel="heavy", max_retries=9, eta=3600
        )._ir_job_test_append()
        self.assertEqual(job.priority, 1)
        self.assertEqual(job.channel, "heavy")
        self.assertEqual(job.max_retries, 9)
        self.assertTrue(job.eta > fields.Datetime.now() + timedelta(minutes=55))

    def test_delayed_rejects_undecorated_method(self):
        with self.assertRaises(UserError):
            self.partner.delayed().write({"name": "nope"})

    def test_delayed_rejects_unserializable_args(self):
        with self.assertRaises(UserError):
            self.partner.delayed()._ir_job_test_append(object())

    def test_context_is_allowlisted(self):
        records = self.partner.with_context(lang="en_US", secret="s3cr3t")
        job = records.delayed()._ir_job_test_append()
        self.assertEqual(job.context.get("lang"), "en_US")
        self.assertNotIn("secret", job.context)

    def test_identity_key_dedup(self):
        first = self.partner.delayed(identity_key="once")._ir_job_test_append()
        twin = self.partner.delayed(identity_key="once")._ir_job_test_append()
        self.assertEqual(first.id, twin.id)
        first.sudo().write({"state": "done"})
        first.env.flush_all()
        third = self.partner.delayed(identity_key="once")._ir_job_test_append()
        self.assertNotEqual(first.id, third.id)

    def test_claim_respects_priority_and_eta(self):
        low = self.partner.delayed(priority=20)._ir_job_test_append()
        high = self.partner.delayed(priority=1)._ir_job_test_append()
        future = self.partner.delayed(priority=0, eta=3600)._ir_job_test_append()

        claimed = self._claim()
        self.assertEqual(claimed["id"], high.id)
        high.invalidate_recordset()
        self.assertEqual(high.state, "started")
        self.assertEqual(high.worker_ident, "test:0")

        self.assertIsNone(self._claim())
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'done' WHERE id = %s", (high.id,)
        )
        claimed = self._claim()
        self.assertEqual(claimed["id"], low.id)

        self.env.cr.execute("UPDATE ir_job SET state = 'done' WHERE id = %s", (low.id,))
        self.assertIsNone(self._claim())
        self.assertEqual(future.state, "pending")

    def test_claim_respects_channel_capacity(self):
        self.partner.delayed(channel="bulk")._ir_job_test_append()
        self.partner.delayed(channel="bulk")._ir_job_test_append()

        self.assertIsNotNone(self._claim())
        self.assertIsNone(self._claim(), "implicit capacity of 1")

        self.env["ir.job.channel"].create({"name": "bulk", "capacity": 2})
        self.env.flush_all()
        self.assertIsNotNone(self._claim(), "explicit capacity of 2")

    def test_run_claimed_executes_and_completes_atomically(self):
        self.partner.delayed()._ir_job_test_append(" ran")
        job = self._claim()
        IrJob._run_claimed(self.env.cr, job)
        self.env.invalidate_all()
        self.assertEqual(self.partner.name, "job target ran")
        record = self.env["ir.job"].browse(job["id"])
        self.assertEqual(record.state, "done")
        self.assertTrue(record.done_at)

    def test_run_claimed_refuses_undecorated_method(self):
        self.partner.delayed()._ir_job_test_append()
        job = self._claim()
        job["method_name"] = "write"
        with self.assertRaises(TypeError):
            IrJob._run_claimed(self.env.cr, job)

    def test_failure_retries_with_backoff_then_fails(self):
        self.partner.delayed(max_retries=1)._ir_job_test_boom(
            retryable=True, seconds=42
        )
        job = self._claim()
        with self.assertRaises(RetryableJobError):
            IrJob._run_claimed(self.env.cr, job)
        IrJob._record_failure(self.env.cr, job, RetryableJobError("x", seconds=42))

        record = self.env["ir.job"].browse(job["id"])
        self.assertEqual(record.state, "pending")
        self.assertEqual(record.retry, 1)
        self.assertEqual(record.exc_name, "RetryableJobError")
        delta = record.eta - fields.Datetime.now()
        self.assertTrue(timedelta(seconds=37) < delta < timedelta(seconds=47))

        self.env.cr.execute("UPDATE ir_job SET eta = NULL WHERE id = %s", (job["id"],))
        job = self._claim()
        self.assertEqual(job["id"], record.id)
        IrJob._record_failure(self.env.cr, job, ValueError("boom"))
        record.invalidate_recordset()
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.exc_name, "ValueError")
        self.assertTrue(record.done_at)

    def test_reaper_requeues_dead_started_jobs(self):
        job = self.partner.delayed()._ir_job_test_append()
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'started',"
            " started_at = (now() AT TIME ZONE 'UTC') - interval '5 minutes'"
            " WHERE id = %s",
            (job.id,),
        )
        IrJob._reap_dead_jobs(self.env.cr)
        job.invalidate_recordset()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.retry, 1)
        self.assertEqual(job.exc_name, "WorkerDied")

    def test_reaper_spares_recent_and_locked_jobs(self):
        fresh = self.partner.delayed()._ir_job_test_append()
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'started',"
            " started_at = (now() AT TIME ZONE 'UTC') WHERE id = %s",
            (fresh.id,),
        )
        IrJob._reap_dead_jobs(self.env.cr)
        fresh.invalidate_recordset()
        self.assertEqual(fresh.state, "started", "inside the grace period")

    def test_reaper_fails_job_with_exhausted_budget(self):
        job = self.partner.delayed(max_retries=0)._ir_job_test_append()
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'started',"
            " started_at = (now() AT TIME ZONE 'UTC') - interval '5 minutes'"
            " WHERE id = %s",
            (job.id,),
        )
        IrJob._reap_dead_jobs(self.env.cr)
        job.invalidate_recordset()
        self.assertEqual(job.state, "failed")

    def test_chain_releases_on_completion(self):
        j1 = self.partner.delayed()._ir_job_test_append(" a")
        j2 = self.partner.delayed(after=j1)._ir_job_test_append(" b")
        self.assertEqual(j2.state, "wait_deps")
        self.assertEqual(j2.depends_on_ids, j1)
        self.assertEqual(j1.dependent_ids, j2)

        claimed = self._claim()
        self.assertEqual(claimed["id"], j1.id, "wait_deps must not be claimable")
        IrJob._run_claimed(self.env.cr, claimed)
        j2.invalidate_recordset()
        self.assertEqual(j2.state, "pending", "released atomically with j1's done")

        claimed = self._claim()
        self.assertEqual(claimed["id"], j2.id)
        IrJob._run_claimed(self.env.cr, claimed)
        self.env.invalidate_all()
        self.assertEqual(self.partner.name, "job target a b")

    def test_fan_in_waits_for_all_dependencies(self):
        j1 = self.partner.delayed()._ir_job_test_append()
        j2 = self.partner.delayed(channel="other")._ir_job_test_append()
        j3 = self.partner.delayed(after=j1 | j2)._ir_job_test_append()

        IrJob._run_claimed(self.env.cr, self._claim())
        j3.invalidate_recordset()
        self.assertEqual(j3.state, "wait_deps", "one of two dependencies done")
        IrJob._run_claimed(self.env.cr, self._claim())
        j3.invalidate_recordset()
        self.assertEqual(j3.state, "pending", "all dependencies done")

    def test_enqueue_after_done_dependency_is_pending(self):
        j1 = self.partner.delayed()._ir_job_test_append()
        IrJob._run_claimed(self.env.cr, self._claim())
        j2 = self.partner.delayed(after=j1)._ir_job_test_append()
        self.assertEqual(j2.state, "pending")

    def test_enqueue_after_failed_dependency_is_refused(self):
        j1 = self.partner.delayed(max_retries=0)._ir_job_test_boom()
        claimed = self._claim()
        IrJob._record_failure(self.env.cr, claimed, ValueError("boom"))
        with self.assertRaises(UserError):
            self.partner.delayed(after=j1)._ir_job_test_append()

    def test_failure_cascade_cancels_transitive_dependents(self):
        j1 = self.partner.delayed(max_retries=0)._ir_job_test_boom()
        j2 = self.partner.delayed(after=j1)._ir_job_test_append()
        j3 = self.partner.delayed(after=j2)._ir_job_test_append()

        claimed = self._claim()
        IrJob._record_failure(self.env.cr, claimed, ValueError("boom"))
        (j1 + j2 + j3).invalidate_recordset()
        self.assertEqual(j1.state, "failed")
        self.assertEqual(j2.state, "cancelled")
        self.assertEqual(j3.state, "cancelled", "cascade is transitive")
        self.assertEqual(j2.exc_name, "DependencyFailed")

    def test_cancel_cascades_to_waiting_dependents(self):
        j1 = self.partner.delayed()._ir_job_test_append()
        j2 = self.partner.delayed(after=j1)._ir_job_test_append()
        j1.action_cancel()
        j2.invalidate_recordset()
        self.assertEqual(j2.state, "cancelled")

    def test_requeue_recomputes_dependency_state(self):
        j1 = self.partner.delayed()._ir_job_test_append()
        j2 = self.partner.delayed(after=j1)._ir_job_test_append()
        j1.action_cancel()
        j2.invalidate_recordset()
        self.assertEqual(j2.state, "cancelled")
        (j1 + j2).action_requeue()
        self.assertEqual(j1.state, "pending")
        self.assertEqual(j2.state, "wait_deps")

    def test_repair_sweep_resolves_stuck_jobs(self):
        j1 = self.partner.delayed()._ir_job_test_append()
        j2 = self.partner.delayed(after=j1)._ir_job_test_append()
        self.env.cr.execute("UPDATE ir_job SET state = 'done' WHERE id = %s", (j1.id,))
        IrJob._resolve_dependencies(self.env.cr)
        j2.invalidate_recordset()
        self.assertEqual(j2.state, "pending")

        j3 = self.partner.delayed()._ir_job_test_append()
        j4 = self.partner.delayed(after=j3)._ir_job_test_append()
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'failed' WHERE id = %s", (j3.id,)
        )
        IrJob._resolve_dependencies(self.env.cr)
        j4.invalidate_recordset()
        self.assertEqual(j4.state, "cancelled")

    def test_requeue_and_cancel_actions(self):
        job = self.partner.delayed()._ir_job_test_append()
        job.action_cancel()
        self.assertEqual(job.state, "cancelled")
        job.action_requeue()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.retry, 0)
        with self.assertRaises(UserError):
            job.action_requeue()

    def test_run_now_executes_pending_job(self):
        job = self.partner.delayed(eta=3600)._ir_job_test_append(" manual")
        job.action_run_now()
        self.assertEqual(job.state, "done")
        self.assertEqual(job.worker_ident, f"manual:{self.env.uid}")
        self.env.invalidate_all()
        self.assertEqual(self.partner.name, "job target manual")
        with self.assertRaises(UserError):
            job.action_run_now()

    def test_run_now_propagates_business_exception(self):
        job = self.partner.delayed()._ir_job_test_boom()
        with self.assertRaises(ValueError):
            job.action_run_now()

    def test_notify_failed_hook_fires_on_permanent_failure(self):
        job = self.partner.delayed(max_retries=0)._ir_job_test_boom()
        claimed = self._claim()
        exc = ValueError("boom")
        with patch.object(IrJob, "_notify_failed") as hook:
            IrJob._record_failure(self.env.cr, claimed, exc)
        hook.assert_called_once()
        job.invalidate_recordset()
        self.assertEqual(job.state, "failed")

    def test_display_name(self):
        job = self.partner.delayed()._ir_job_test_append()
        self.assertEqual(
            job.display_name, f"res.partner._ir_job_test_append (#{job.id})"
        )

    def test_gc_prunes_finished_jobs_by_retention(self):
        done_old = self.partner.delayed()._ir_job_test_append()
        failed_recent = self.partner.delayed()._ir_job_test_append()
        pending = self.partner.delayed()._ir_job_test_append()
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'done',"
            " done_at = (now() AT TIME ZONE 'UTC') - interval '8 days'"
            " WHERE id = %s",
            (done_old.id,),
        )
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'failed',"
            " done_at = (now() AT TIME ZONE 'UTC') - interval '8 days'"
            " WHERE id = %s",
            (failed_recent.id,),
        )
        self.env.invalidate_all()
        removed, more = self.env["ir.job"]._gc_jobs()
        self.assertEqual(removed, 1)
        self.assertFalse(more)
        self.assertFalse(done_old.exists(), "past done retention → pruned")
        self.assertTrue(failed_recent.exists(), "failed keeps the longer window")
        self.assertTrue(pending.exists())

    def test_job_decorator_requires_private_method(self):
        with self.assertRaises(TypeError):

            @api.job
            def public_method(self):
                pass


class TestIrJobDependencyCycle(TransactionCase):
    """Dependency loops are refused, not left running forever."""

    def setUp(self):
        super().setUp()
        _isolate_queue(self.env)

    def test_direct_cycle_is_refused(self):
        """a -> b -> a leaves both jobs in wait_deps for good, so refuse it.

        ``_resolve_dependencies`` only promotes a job whose dependencies are all
        ``done`` and ``_gc_jobs`` only prunes terminal states, so a cycle is
        never run, never cancelled and never collected.
        """
        job_a = self.env["ir.job"].delayed()._job_ping("a")
        job_b = self.env["ir.job"].delayed(after=job_a)._job_ping("b")
        with self.assertRaises(ValidationError):
            job_a.depends_on_ids = job_b

    def test_indirect_cycle_is_refused(self):
        """a -> b -> c -> a is caught too, not just the two-node case."""
        job_a = self.env["ir.job"].delayed()._job_ping("a")
        job_b = self.env["ir.job"].delayed(after=job_a)._job_ping("b")
        job_c = self.env["ir.job"].delayed(after=job_b)._job_ping("c")
        with self.assertRaises(ValidationError):
            job_a.depends_on_ids = job_c

    def test_cycle_via_the_reverse_side_is_refused(self):
        """``dependent_ids`` writes the same rows from the other end.

        Watching only ``depends_on_ids`` left this side open, so the same loop
        could still be built through the reverse field.
        """
        job_a = self.env["ir.job"].delayed()._job_ping("a")
        job_b = self.env["ir.job"].delayed(after=job_a)._job_ping("b")
        with self.assertRaises(ValidationError):
            job_b.dependent_ids = job_a

    def test_self_dependency_is_refused(self):
        """A job depending on itself never becomes runnable either."""
        job = self.env["ir.job"].delayed()._job_ping("solo")
        with self.assertRaises(ValidationError):
            job.depends_on_ids = job

    def test_diamond_dependencies_are_allowed(self):
        """Fan-out/fan-in is not a cycle and must keep working."""
        root = self.env["ir.job"].delayed()._job_ping("root")
        left = self.env["ir.job"].delayed(after=root)._job_ping("left")
        right = self.env["ir.job"].delayed(after=root)._job_ping("right")
        join = self.env["ir.job"].delayed(after=left | right)._job_ping("join")
        self.env.flush_all()
        self.assertEqual(join.state, "wait_deps")
        self.assertEqual(join.depends_on_ids, left | right)


class TestIrJobClaimSnapshot(BaseCase):
    """Claiming from a transaction whose snapshot predates another claim."""

    def setUp(self):
        super().setUp()
        self.registry = Registry(common.get_db_name())
        self.addCleanup(self._clear_jobs)
        self._clear_jobs()
        with self.registry.cursor() as cr:
            env = odoo.api.Environment(cr, common.ADMIN_USER_ID, {})
            env["ir.job.channel"].create({"name": "claimtest", "capacity": 100})
            cr.execute(
                "INSERT INTO ir_job (channel, state, priority, model_name,"
                " method_name, user_id, max_retries, retry, create_uid,"
                " create_date, write_uid, write_date) VALUES"
                " ('claimtest','pending',1,'ir.job','_job_ping',1,5,0,1,now(),1,now()),"
                " ('claimtest','pending',2,'ir.job','_job_ping',1,5,0,1,now(),1,now())"
            )

    def _clear_jobs(self):
        with self.registry.cursor() as cr:
            cr.execute("DELETE FROM ir_job_dependency")
            cr.execute("DELETE FROM ir_job WHERE channel = 'claimtest'")
            cr.execute("DELETE FROM ir_job_channel WHERE name = 'claimtest'")

    @mute_logger("odoo.db.cursor")
    def test_claim_recovers_from_a_stale_snapshot(self):
        """A claimer whose snapshot predates the winner's commit still claims.

        ``pg_advisory_xact_lock`` is the claim transaction's first statement, so
        it pins the ``REPEATABLE READ`` snapshot; whoever waits on the lock
        resumes with a snapshot older than the winner's commit and its
        ``UPDATE`` fails with ``40001``.  ``_claim_next`` must roll back for a
        fresh snapshot and retry, not propagate -- the exception escaped
        ``_claim_and_run_loop`` and ended the whole worker pass.
        """
        with self.registry.cursor() as cr_a, self.registry.cursor() as cr_b:
            cr_b.execute("SELECT count(*) FROM ir_job")  # pin B's snapshot

            job_a = IrJob._claim_next(cr_a, "snap:a", channels=["claimtest"])
            cr_a.commit()
            self.assertIsNotNone(job_a)

            job_b = IrJob._claim_next(cr_b, "snap:b", channels=["claimtest"])
            cr_b.commit()
            self.assertIsNotNone(job_b, "the stale-snapshot claimer got nothing")
            self.assertNotEqual(job_b["id"], job_a["id"])


class TestIrJobEnqueueTarget(TransactionCase):
    """``delayed()`` must not accept a target it cannot persist."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_cls = type(cls.env["res.partner"])
        setattr(cls.partner_cls, _ir_job_test_append.__name__, _ir_job_test_append)
        cls.addClassCleanup(delattr, cls.partner_cls, _ir_job_test_append.__name__)
        _isolate_queue(cls.env)

    def test_unsaved_records_are_refused(self):
        """``ids`` drops ``NewId``, so this used to enqueue an empty target: a
        job that ran against no record, did nothing and reported success.
        """
        unsaved = self.env["res.partner"].new({"name": "never saved"})
        self.assertEqual(len(unsaved), 1)
        self.assertEqual(unsaved.ids, [])
        with self.assertRaises(UserError):
            unsaved.delayed()._ir_job_test_append("x")

    def test_saved_records_are_still_accepted(self):
        partner = self.env["res.partner"].create({"name": "saved"})
        job = partner.delayed()._ir_job_test_append("x")
        self.assertEqual(job.record_ids, partner.ids)

    def test_model_level_enqueue_is_still_accepted(self):
        """An empty recordset is a legitimate model-level target."""
        job = self.env["ir.job"].delayed()._job_ping("hi")
        self.assertEqual(job.record_ids, [])


class TestIrJobClaimCapacity(TransactionCase):
    """The claim query's capacity decision, and that the ``saturated`` CTE
    reproduces it for every channel shape.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _isolate_queue(cls.env)

    def _job(self, channel, state, priority, started=False):
        job = self.env["ir.job"].create(
            {
                "channel": channel,
                "state": state,
                "priority": priority,
                "model_name": "ir.job",
                "method_name": "_job_ping",
                "user_id": self.env.uid,
                "max_retries": 0,
            }
        )
        if started:
            job.started_at = fields.Datetime.now()
        return job

    def test_capacity_is_respected_across_channel_shapes(self):
        self.env["ir.job.channel"].create(
            [
                {"name": "cap2", "capacity": 2},
                {"name": "cap3", "capacity": 3},
                {"name": "off", "capacity": 9, "active": False},
            ]
        )
        for channel, running in (("cap2", 2), ("cap3", 1), ("off", 1)):
            for _ in range(running):
                self._job(channel, "started", 1, started=True)
        wanted = {}
        for priority, channel in enumerate(
            ("cap2", "off", "cap3", "implicit"), start=1
        ):
            wanted[channel] = self._job(channel, "pending", priority).id
        self.env.flush_all()

        claimed = []
        while job := IrJob._claim_next(
            self.env.cr, "cap:0", channels=["cap2", "cap3", "off", "implicit"]
        ):
            claimed.append(job["id"])

        self.assertEqual(
            claimed,
            [wanted["cap3"], wanted["implicit"]],
            "only the channels below capacity are claimable, in priority order",
        )

    def test_backlog_behind_a_saturated_channel_does_not_hide_a_runnable_job(self):
        """The runnable job is worst-priority, so every blocked row is scanned
        before it: the regression this guards is a per-row capacity recount.
        """
        self.env["ir.job.channel"].create({"name": "full", "capacity": 1})
        self._job("full", "started", 1, started=True)
        for _ in range(50):
            self._job("full", "pending", 1)
        runnable = self._job("free", "pending", 99).id
        self.env.flush_all()

        job = IrJob._claim_next(self.env.cr, "cap:1", channels=["full", "free"])
        self.assertIsNotNone(job)
        self.assertEqual(job["id"], runnable)
