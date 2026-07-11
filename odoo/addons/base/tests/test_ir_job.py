"""Tests of the framework job queue (``ir.job``).

Everything runs on the test cursor: ``_claim_next`` / ``_run_claimed`` /
``_record_failure`` / ``_reap_dead_jobs`` all take an explicit ``cr`` so the
whole claim/execute/finalize state machine is exercised inside the test
transaction, without workers or extra connections.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import api, fields
from odoo.exceptions import RetryableJobError, UserError
from odoo.tests.common import TransactionCase

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


class TestIrJob(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Graft @api.job methods onto the registry class of res.partner: tests
        # need decorated methods, and shipping test-only jobs in base would
        # put them on every production model.
        cls.partner_cls = type(cls.env["res.partner"])
        for func in (_ir_job_test_append, _ir_job_test_boom):
            setattr(cls.partner_cls, func.__name__, func)
            cls.addClassCleanup(delattr, cls.partner_cls, func.__name__)
        cls.partner = cls.env["res.partner"].create({"name": "job target"})

    def _claim(self):
        return IrJob._claim_next(self.env.cr, "test:0")

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def test_delayed_enqueues_pending_job(self):
        job = self.partner.delayed()._ir_job_test_append("?")
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.model_name, "res.partner")
        self.assertEqual(job.method_name, "_ir_job_test_append")
        self.assertEqual(job.record_ids, self.partner.ids)
        self.assertEqual(job.args, ["?"])
        self.assertEqual(job.kwargs, {})
        # decorator defaults
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
        # a finished twin no longer blocks re-enqueueing
        first.sudo().write({"state": "done"})
        first.env.flush_all()
        third = self.partner.delayed(identity_key="once")._ir_job_test_append()
        self.assertNotEqual(first.id, third.id)

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    def test_claim_respects_priority_and_eta(self):
        low = self.partner.delayed(priority=20)._ir_job_test_append()
        high = self.partner.delayed(priority=1)._ir_job_test_append()
        future = self.partner.delayed(priority=0, eta=3600)._ir_job_test_append()

        claimed = self._claim()
        self.assertEqual(claimed["id"], high.id)
        high.invalidate_recordset()
        self.assertEqual(high.state, "started")
        self.assertEqual(high.worker_ident, "test:0")

        # root capacity is 1 (implicit): nothing else claimable while started
        self.assertIsNone(self._claim())
        self.env.cr.execute(
            "UPDATE ir_job SET state = 'done' WHERE id = %s", (high.id,)
        )
        claimed = self._claim()
        self.assertEqual(claimed["id"], low.id)

        # the future job stays out of reach regardless
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

    # ------------------------------------------------------------------
    # Execute / finalize
    # ------------------------------------------------------------------

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
        job["method_name"] = "write"  # simulate a tampered row
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
        # explicit delay honored (±5s slack for the test clock)
        delta = record.eta - fields.Datetime.now()
        self.assertTrue(timedelta(seconds=37) < delta < timedelta(seconds=47))

        # budget exhausted (max_retries=1): next failure is final
        self.env.cr.execute("UPDATE ir_job SET eta = NULL WHERE id = %s", (job["id"],))
        job = self._claim()
        self.assertEqual(job["id"], record.id)
        IrJob._record_failure(self.env.cr, job, ValueError("boom"))
        record.invalidate_recordset()
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.exc_name, "ValueError")
        self.assertTrue(record.done_at)

    # ------------------------------------------------------------------
    # Reaper
    # ------------------------------------------------------------------

    def test_reaper_requeues_dead_started_jobs(self):
        job = self.partner.delayed()._ir_job_test_append()
        # a worker died 5 minutes ago: started, stale, no advisory lock held
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

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def test_requeue_and_cancel_actions(self):
        job = self.partner.delayed()._ir_job_test_append()
        job.action_cancel()
        self.assertEqual(job.state, "cancelled")
        job.action_requeue()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.retry, 0)
        with self.assertRaises(UserError):
            job.action_requeue()  # pending → not requeueable

    def test_run_now_executes_pending_job(self):
        job = self.partner.delayed(eta=3600)._ir_job_test_append(" manual")
        job.action_run_now()  # eta deliberately ignored
        self.assertEqual(job.state, "done")
        self.assertEqual(job.worker_ident, f"manual:{self.env.uid}")
        self.env.invalidate_all()
        self.assertEqual(self.partner.name, "job target manual")
        with self.assertRaises(UserError):
            job.action_run_now()  # done → not runnable again

    def test_run_now_propagates_business_exception(self):
        job = self.partner.delayed()._ir_job_test_boom()
        # the exception reaches the user; in a real request the transaction
        # (including the inline claim) rolls back, leaving the job pending
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

    def test_job_decorator_requires_private_method(self):
        with self.assertRaises(TypeError):

            @api.job
            def public_method(self):
                pass
