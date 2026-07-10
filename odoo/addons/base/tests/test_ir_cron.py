import contextlib
import secrets
import textwrap
import time
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

import odoo
from odoo import fields
from odoo.exceptions import UserError
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase, Like, RecordCapturer, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_cron import (
    MAX_FAIL_TIME,
    MIN_DELTA_BEFORE_DEACTIVATION,
    MIN_FAILURE_COUNT_BEFORE_DEACTIVATION,
    MIN_RUNS_PER_JOB,
    MIN_TIME_PER_JOB,
    PROGRESS_RETENTION_PERIOD,
    TRIGGER_RETENTION_PERIOD,
    BadModuleStateError,
    BadVersionError,
    CompletionStatus,
    IrCron,
)
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class CronMixinCase:
    def capture_triggers(self, cron_id=None):
        """Return a context manager capturing cron triggers created within it.

        Captured triggers are exposed on the returned object's `records`
        attribute; nothing is captured once the context exits.

        :param cron_id: optional cron id (int) or xmlid (str) to filter by.
        """
        if isinstance(cron_id, str):  # xmlid case
            cron_id = self.env.ref(cron_id).id

        return RecordCapturer(
            model=self.env["ir.cron.trigger"].sudo(),
            domain=[("cron_id", "=", cron_id)] if cron_id else [],
        )

    @classmethod
    def _get_cron_data(cls, env, priority=5):
        unique = secrets.token_urlsafe(8)
        return {
            "name": f"Dummy cron for TestIrCron {unique}",
            "state": "code",
            "code": "",
            "model_id": env.ref("base.model_res_partner").id,
            "model_name": "res.partner",
            "user_id": env.uid,
            "active": True,
            "interval_number": 1,
            "interval_type": "days",
            "nextcall": fields.Datetime.now() + timedelta(hours=1),
            "lastcall": False,
            "priority": priority,
        }

    @classmethod
    def _get_partner_data(cls, env):
        unique = secrets.token_urlsafe(8)
        return {"name": f"Dummy partner for TestIrCron {unique}"}


class TestIrCron(TransactionCase, CronMixinCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        freezer = freeze_time(cls.cr.now())
        cls.frozen_datetime = freezer.start()
        cls.addClassCleanup(freezer.stop)

        cls.cron = cls.env["ir.cron"].create(cls._get_cron_data(cls.env))
        cls.partner = cls.env["res.partner"].create(cls._get_partner_data(cls.env))

    def setUp(self):
        super().setUp()
        self.partner.write(self._get_partner_data(self.env))
        self.cron.write(self._get_cron_data(self.env))

        domain = [("cron_id", "=", self.cron.id)]
        self.env["ir.cron.trigger"].search(domain).unlink()
        self.env["ir.cron.progress"].search(domain).unlink()

        # pin cr.now() to the frozen datetime so "remaining jobs after some
        # time" is deterministic
        self.patch(self.env.cr, "now", self.frozen_datetime)

    def _acquire_job(self, cr, cron=None):
        """Build the ``job`` dict through the real production acquire path.

        ``_acquire_one_job`` uses ``dictfetchone``, so SQL NULL comes back as
        ``None``; fabricating from ``read(load=None)`` yields ``False`` for NULL
        columns (e.g. ``first_failure_date``) — a shape production never
        produces, which masked a dropped ``deactivate`` write (see
        ``test_cron_deactivate_production_shape``). Acquires with
        ``include_not_ready=True`` so tests need not ready the cron first. In
        registry test mode ``cr`` shares the test connection, so its row lock
        cannot deadlock with the test cursor.
        """
        cron = cron if cron is not None else self.cron
        self.env.flush_all()
        job = self.registry["ir.cron"]._acquire_one_job(
            cr, cron.id, include_not_ready=True
        )
        self.assertIsNotNone(job, "the test cron must be acquirable")
        return job

    def test_cron_direct_trigger(self):
        self.cron.code = textwrap.dedent(f"""\
            model.search(
                [("id", "=", {self.partner.id})]
            ).write(
                {{"name": "You have been CRONWNED"}}
            )
        """)

        registry = self.cron.pool
        with (
            self.enter_registry_test_mode(),
            patch.object(
                registry, "cursor", side_effect=registry.cursor, autospec=True
            ) as cursor_method,
        ):
            self.cron.method_direct_trigger()
            self.assertEqual(
                cursor_method.call_count,
                1,
                "Should create a new transaction for direct trigger",
            )

        self.assertEqual(self.cron.lastcall, fields.Datetime.now())
        self.assertEqual(self.partner.name, "You have been CRONWNED")

    def test_cron_direct_trigger_exception(self):
        self.cron.code = textwrap.dedent("raise UserError('oops')")
        with (
            self.enter_registry_test_mode(),
            self.assertLogs("odoo.addons.base.models.ir_cron", 40),  # logging.ERROR
            self.registry.cursor() as cron_cr,
        ):
            action = self.cron.with_env(self.env(cr=cron_cr)).method_direct_trigger()

        self.assertNotEqual(action, True)
        action_params = action.pop("params")
        self.assertEqual(
            action, {"type": "ir.actions.client", "tag": "display_exception"}
        )
        self.assertEqual(list(action_params), ["code", "message", "data"])
        self.assertEqual(
            list(action_params["data"]),
            ["name", "message", "arguments", "context", "debug"],
        )

    def test_cron_no_job_ready(self):
        self.cron.nextcall = fields.Datetime.now() + timedelta(days=1)
        self.cron.flush_recordset()

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertNotIn(self.cron.id, [job["id"] for job in ready_jobs])

    def test_cron_ready_by_nextcall(self):
        self.cron.nextcall = fields.Datetime.now()
        self.cron.flush_recordset()

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertIn(self.cron.id, [job["id"] for job in ready_jobs])

    def test_cron_ready_by_trigger(self):
        self.cron._trigger()
        self.env["ir.cron.trigger"].flush_model()

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertIn(self.cron.id, [job["id"] for job in ready_jobs])

    def test_cron_unactive_never_ready(self):
        self.cron.active = False
        self.cron.nextcall = fields.Datetime.now()
        self.env.flush_all()

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertNotIn(self.cron.id, [job["id"] for job in ready_jobs])

    def test_cron_ready_jobs_order(self):
        cron_avg = self.cron.copy()
        cron_avg.priority = 5  # average priority

        cron_high = self.cron.copy()
        cron_high.priority = 0  # highest priority

        cron_low = self.cron.copy()
        cron_low.priority = 10  # lowest priority

        crons = cron_high | cron_avg | cron_low  # order is important
        crons.write({"nextcall": fields.Datetime.now()})
        crons.flush_recordset()
        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)

        self.assertEqual(
            [job["id"] for job in ready_jobs if job["id"] in crons._ids],
            list(crons._ids),
        )

    def test_cron_skip_unactive_triggers(self):
        # Admin disabled the cron, another user triggers it *now*: the cron
        # must not be ready and the trigger must not be stored.
        self.cron.active = False
        self.cron.nextcall = fields.Datetime.now() + timedelta(days=2)
        self.cron.flush_recordset()
        with self.capture_triggers() as capture:
            self.cron._trigger()

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertNotIn(
            self.cron.id,
            [job["id"] for job in ready_jobs],
            "the cron shouldn't be ready",
        )
        self.assertFalse(capture.records, "trigger should has been skipped")

    def test_cron_keep_future_triggers(self):
        # Yesterday an admin disabled the cron; while disabled another user
        # triggered it to run today. Re-enabled before today, it should run.

        # go yesterday
        self.frozen_datetime.tick(delta=timedelta(days=-1))

        # admin disable the cron
        self.cron.active = False
        self.cron.nextcall = fields.Datetime.now() + timedelta(days=10)
        self.cron.flush_recordset()

        # user triggers the cron to run *tomorrow of yesterday (=today)
        with self.capture_triggers() as capture:
            self.cron._trigger(at=fields.Datetime.now() + timedelta(days=1))

        # admin re-enable the cron
        self.cron.active = True
        self.cron.flush_recordset()

        # go today, check the cron should run
        self.frozen_datetime.tick(delta=timedelta(days=1))
        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertIn(
            self.cron.id,
            [job["id"] for job in ready_jobs],
            "cron should be ready",
        )
        self.assertTrue(capture.records, "trigger should has been kept")

    def test_trigger_call_at_uses_db_transaction_clock(self):
        # _trigger must stamp call_at from the DB transaction clock (cr.now),
        # NOT the process wall clock, so writer and "is it due" reader agree
        # even when the app host clock differs from the DB's (or lacks tzset).
        db_time = datetime(2020, 1, 1, 12, 0, 0)
        self.patch(self.env.cr, "now", lambda: db_time)
        with self.capture_triggers(self.cron.id) as capture:
            self.cron._trigger()
        self.assertEqual(
            capture.records.call_at,
            db_time,
            "trigger call_at must come from cr.now(), not fields.Datetime.now()",
        )

    def test_toggle_sets_active_from_domain_existence(self):
        # Also guards the search_count(limit=1) existence-check optimisation.
        self.env["ir.config_parameter"].sudo().set_param("database.is_neutralized", "")
        self.cron.write({"active": False})
        self.cron.toggle("res.partner", [("id", "=", self.partner.id)])
        self.assertTrue(self.cron.active, "matching domain -> cron enabled")
        self.cron.toggle("res.partner", [("id", "=", 0)])
        self.assertFalse(self.cron.active, "empty domain -> cron disabled")

    def test_toggle_noop_on_neutralized_database(self):
        # On a neutralized DB, toggle must never re-enable a disabled cron.
        self.env["ir.config_parameter"].sudo().set_param("database.is_neutralized", "1")
        self.cron.write({"active": False})
        self.cron.toggle("res.partner", [("id", "=", self.partner.id)])
        self.assertFalse(
            self.cron.active, "neutralized DB -> toggle is a no-op, stays disabled"
        )

    def test_cron_process_job(self):
        Progress = self.env["ir.cron.progress"]
        ten_days_ago = (
            fields.Datetime.now() - MIN_DELTA_BEFORE_DEACTIVATION - timedelta(days=2)
        )
        almost_failed = MIN_FAILURE_COUNT_BEFORE_DEACTIVATION - 1
        frozen_datetime = self.frozen_datetime

        def nothing(cron):
            state = {"call_count": 0}

            def f(self):
                state["call_count"] += 1

            return f, state

        def eleven_success(cron):
            state = {"call_count": 0}
            CALL_TARGET = 11

            def f(self):
                frozen_datetime.tick(delta=timedelta(seconds=1))
                state["call_count"] += 1
                self.env["ir.cron"]._commit_progress(
                    processed=1, remaining=CALL_TARGET - state["call_count"]
                )

            return f, state

        def five_success(cron):
            state = {"call_count": 0}
            CALL_TARGET = 5

            def f(self):
                state["call_count"] += 1
                self.env["ir.cron"]._commit_progress(
                    processed=1, remaining=CALL_TARGET - state["call_count"]
                )

            return f, state

        def end_time(cron):
            state = {
                "call_count": 0,
                "remaining": MIN_TIME_PER_JOB + 1,
            }

            def f(self):
                state["call_count"] += 1
                while self.env["ir.cron"]._commit_progress(
                    remaining=state["remaining"]
                ):
                    state["remaining"] -= 1
                    frozen_datetime.tick(delta=timedelta(seconds=1))
                    self.env["ir.cron"]._commit_progress(1)

            return f, state

        def failure(cron):
            state = {"call_count": 0}

            def f(self):
                state["call_count"] += 1
                raise ValueError

            return f, state

        def failure_partial(cron):
            state = {"call_count": 0}
            CALL_TARGET = 5

            def f(self):
                state["call_count"] += 1
                self.env["ir.cron"]._commit_progress(
                    processed=1, remaining=CALL_TARGET - state["call_count"]
                )
                self.env.cr.commit()
                raise ValueError

            return f, state

        def failure_fully(cron):
            state = {"call_count": 0}

            def f(self):
                state["call_count"] += 1
                self.env["ir.cron"]._commit_progress(1, remaining=0)
                self.env.cr.commit()
                raise ValueError

            return f, state

        CASES = [
            #                 IN          |                 OUT
            #       callback, curr_failures, trigger, call_count, done_count, fail_count, active,
            (nothing, 0, False, 1, 0, 0, True),
            (nothing, almost_failed, False, 1, 0, 0, True),
            (eleven_success, 0, True, 10, 10, 0, True),
            (eleven_success, almost_failed, True, 10, 10, 0, True),
            (five_success, 0, False, 5, 5, 0, True),
            (five_success, almost_failed, False, 5, 5, 0, True),
            (end_time, 0, True, 2, 10, 0, True),
            (failure, 0, False, 1, 0, 1, True),
            (failure, almost_failed, False, 1, 0, 0, False),
            (failure_partial, 0, False, 5, 5, 1, True),
            (failure_partial, almost_failed, False, 5, 5, 0, False),
            (failure_fully, 0, False, 1, 1, 1, True),
            (failure_fully, almost_failed, False, 1, 1, 0, False),
        ]

        for (
            cb,
            curr_failures,
            trigger,
            call_count,
            done_count,
            fail_count,
            active,
        ) in CASES:
            with (
                self.subTest(cb=cb, failure=curr_failures),
                closing(self.cr.savepoint()),
            ):
                self.cron.write(
                    {
                        "active": True,
                        "failure_count": curr_failures,
                        "first_failure_date": (ten_days_ago if curr_failures else None),
                    }
                )
                with self.capture_triggers(self.cron.id) as capture:
                    if trigger:
                        self.cron._trigger()

                self.env.flush_all()
                with self.enter_registry_test_mode():
                    cb, state = cb(self.cron)
                    with (
                        mute_logger("odoo.addons.base.models.ir_cron"),
                        patch.object(self.registry["ir.actions.server"], "run", cb),
                        self.registry.cursor() as cr,
                    ):
                        self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))
                self.cron.invalidate_recordset()
                capture.records.invalidate_recordset()

                self.assertEqual(
                    self.cron.id
                    in [
                        job["id"] for job in self.cron._get_all_ready_jobs(self.env.cr)
                    ],
                    trigger,
                )
                self.assertEqual(state["call_count"], call_count)
                self.assertEqual(
                    sum(
                        Progress.search(
                            [("cron_id", "=", self.cron.id), ("done", ">=", 1)]
                        ).mapped("done")
                    ),
                    done_count,
                )
                self.assertEqual(self.cron.failure_count, fail_count)
                self.assertEqual(self.cron.active, active)

    def test_cron_retrigger(self):
        Trigger = self.env["ir.cron.trigger"]
        Progress = self.env["ir.cron.progress"]
        frozen_datetime = self.frozen_datetime

        CALL_TARGET = 31
        mocked_run_state = {"call_count": 0, "duration": 0}

        def mocked_run(self):
            frozen_datetime.tick(delta=timedelta(seconds=mocked_run_state["duration"]))
            mocked_run_state["call_count"] += 1
            self.env["ir.cron"]._commit_progress(
                processed=1,
                remaining=CALL_TARGET - mocked_run_state["call_count"],
            )

        self.cron._trigger()
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.actions.server"], "run", mocked_run),
            self.registry.cursor() as cr,
        ):
            # make each run 2 seconds, so that it is run 10 times, 20 seconds in total
            mocked_run_state["duration"] = 2
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.assertEqual(
            mocked_run_state["call_count"],
            10,
            "`run` should have been called 10 times",
        )
        self.assertEqual(
            Progress.search_count([("done", "=", 1), ("cron_id", "=", self.cron.id)]),
            10,
            "There should be 10 progress log for this cron",
        )
        self.assertEqual(
            Trigger.search_count([("cron_id", "=", self.cron.id)]),
            1,
            "One trigger should have been kept",
        )

        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.actions.server"], "run", mocked_run),
            self.registry.cursor() as cr,
        ):
            # make each run 0.5 seconds, so that it is run 20 times, 10 seconds in total
            mocked_run_state["duration"] = 0.5
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.assertEqual(
            mocked_run_state["call_count"],
            30,
            "`run` should have been called 10 times",
        )
        self.assertEqual(
            Progress.search_count([("done", "=", 1), ("cron_id", "=", self.cron.id)]),
            30,
            "There should be 30 progress log for this cron",
        )
        self.assertEqual(
            Trigger.search_count([("cron_id", "=", self.cron.id)]),
            1,
            "One trigger should have been kept",
        )

        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.actions.server"], "run", mocked_run),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        ready_jobs = self.registry["ir.cron"]._get_all_ready_jobs(self.cr)
        self.assertNotIn(
            self.cron.id,
            [job["id"] for job in ready_jobs],
            "The cron has finished executing",
        )
        self.assertEqual(
            mocked_run_state["call_count"],
            31,
            "`run` should have been called one additional time",
        )
        self.assertEqual(
            Progress.search_count([("done", "=", 1), ("cron_id", "=", self.cron.id)]),
            31,
            "There should be 31 progress logs for this cron",
        )

    def test_cron_failed_increase(self):
        self.cron._trigger()
        self.env.flush_all()
        with self.enter_registry_test_mode():
            with (
                patch.object(
                    self.registry["ir.cron"], "_callback", side_effect=Exception
                ),
                patch.object(self.registry["ir.cron"], "_notify_admin") as notify,
                mute_logger("odoo.addons.base.models.ir_cron"),
                self.registry.cursor() as cr,
            ):
                self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(self.cron.failure_count, 1, "The cron should have failed once")
        self.assertEqual(self.cron.active, True, "The cron should still be active")
        self.assertFalse(notify.called)

        self.cron.failure_count = 4

        self.cron._trigger()
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.cron"], "_callback", side_effect=Exception),
            patch.object(self.registry["ir.cron"], "_notify_admin") as notify,
            mute_logger("odoo.addons.base.models.ir_cron"),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(
            self.cron.failure_count,
            5,
            "The cron should have failed one more time but not reset (due to time)",
        )
        self.assertEqual(
            self.cron.active,
            True,
            "The cron should not have been deactivated due to time constraint",
        )
        self.assertFalse(notify.called)

        self.cron.failure_count = 4
        self.cron.first_failure_date = fields.Datetime.now() - timedelta(days=8)

        self.cron._trigger()
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.cron"], "_callback", side_effect=Exception),
            patch.object(self.registry["ir.cron"], "_notify_admin") as notify,
            mute_logger("odoo.addons.base.models.ir_cron"),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(
            self.cron.failure_count,
            0,
            "The cron should have failed one more time and reset to 0",
        )
        self.assertEqual(
            self.cron.active,
            False,
            "The cron should have been deactivated after 5 failures",
        )
        self.assertTrue(notify.called)

    def test_cron_timeout_failure(self):
        self.cron._trigger()
        # `_acquire_one_job` joins the latest progress row, so acquired job
        # dicts carry this row's `progress_id`/`done`/`remaining`/
        # `timed_out_counter`, as in production.
        self.env["ir.cron.progress"].create(
            [
                {
                    "cron_id": self.cron.id,
                    "remaining": 0,
                    "done": 0,
                    "timed_out_counter": 3,
                }
            ]
        )
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            mute_logger("odoo.addons.base.models.ir_cron"),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(self.cron.failure_count, 1, "The cron should have failed once")
        self.assertEqual(self.cron.active, True, "The cron should still be active")

        self.cron._trigger()
        with self.enter_registry_test_mode(), self.registry.cursor() as cr:
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(
            self.cron.failure_count,
            0,
            "The cron should have succeeded and reset the counter",
        )

    def test_cron_timeout_success(self):
        self.cron._trigger()
        # `_acquire_one_job` joins the latest progress row, so acquired job
        # dicts carry this row's `progress_id`/`done`/`remaining`/
        # `timed_out_counter`, as in production.
        self.env["ir.cron.progress"].create(
            [
                {
                    "cron_id": self.cron.id,
                    "remaining": 0,
                    "done": 0,
                    "timed_out_counter": 3,
                }
            ]
        )
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            mute_logger("odoo.addons.base.models.ir_cron"),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(self.cron.failure_count, 1, "The cron should have failed once")
        self.assertEqual(self.cron.active, True, "The cron should still be active")

        self.cron._trigger()
        with self.enter_registry_test_mode(), self.registry.cursor() as cr:
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertEqual(
            self.cron.failure_count,
            0,
            "The cron should have succeeded and reset the counter",
        )

    def test_acquire_processed_job(self):
        job = self.env["ir.cron"]._acquire_one_job(self.cr, self.cron.id)
        self.assertEqual(
            job, None, "No error should be thrown, job should just be none"
        )

    @contextlib.contextmanager
    def patch_cron_process_jobs_loop(self):
        """Yield a simplified function for testing `_process_jobs_loop`."""
        self.cron.active = True
        self.cron.search(
            [("id", "not in", self.cron.ids)]
        ).active = False  # deactivate all other for the test
        with (
            self.enter_registry_test_mode(),
            self.registry.cursor() as cr,
        ):

            def process_jobs(**kw):
                kw.setdefault("job_ids", self.cron.ids)
                return IrCron._process_jobs_loop(cr, **kw)

            yield process_jobs

    def patch_run_job(self, return_value=CompletionStatus.FULLY_DONE):
        return patch.object(
            self.registry["ir.cron"], "_run_job", return_value=return_value
        )

    def test_cron_process_jobs_simple(self):
        with (
            self.patch_cron_process_jobs_loop() as process_jobs,
            self.patch_run_job() as run,
        ):
            cron = self.cron.create(self._get_cron_data(self.env))
            cron._trigger()
            self.cron._trigger()
            job_ids = cron.ids + self.cron.ids
            process_jobs(job_ids=job_ids)
            self.assertTrue(
                all(
                    any(job_id == call.args[0]["id"] for call in run.mock_calls)
                    for job_id in job_ids
                ),
                "all jobs called at least once",
            )

    def test_cron_process_jobs_status_partial(self):
        with (
            self.patch_cron_process_jobs_loop() as process_jobs,
            self.patch_run_job(CompletionStatus.PARTIALLY_DONE) as run,
        ):
            self.cron._trigger()
            process_jobs()
            run.assert_called_once()

    def test_cron_process_jobs_status_failed(self):
        with (
            self.patch_cron_process_jobs_loop() as process_jobs,
            self.patch_run_job(CompletionStatus.FAILED) as run,
        ):
            self.cron._trigger()
            process_jobs()
            run.assert_called_once()

    def test_cron_process_jobs_locked(self):
        with (
            self.patch_cron_process_jobs_loop() as process_jobs,
            self.patch_run_job() as run,
            # simulate that record is locked
            patch.object(IrCron, "_acquire_one_job", return_value=None) as acquire,
            patch.object(time, "monotonic", side_effect=lambda: 42 + run.call_count),
        ):
            self.cron._trigger()
            process_jobs()
            run.assert_not_called()
            acquire.assert_called_once()

    def test_cron_commit_progress(self):
        with self.enter_registry_test_mode(), self.registry.cursor() as cr:
            cron = self.cron.with_env(
                self.cron.env(cr=cr, context={"cron_id": self.cron.id})
            )

            # check remaining time
            cron, progress = cron._add_progress()
            result = cron._commit_progress()
            self.assertEqual(result, float("inf"))
            result = cron.with_context(
                cron_end_time=time.monotonic() - 1
            )._commit_progress()
            self.assertEqual(result, 0)

            # check remaining count
            cron, progress = cron._add_progress()
            cron._commit_progress(remaining=5)
            self.assertEqual(progress.done, 0)
            self.assertEqual(progress.remaining, 5)
            cron._commit_progress(processed=3, remaining=7)
            self.assertEqual(progress.done, 3)
            self.assertEqual(progress.remaining, 7)

            # check processed count
            cron, progress = cron._add_progress()
            cron._commit_progress(remaining=5)
            cron._commit_progress(2)
            self.assertEqual(progress.done, 2)
            self.assertEqual(progress.remaining, 3)
            cron._commit_progress(2)
            self.assertEqual(progress.done, 4)
            self.assertEqual(progress.remaining, 1)
            cron._commit_progress(2)
            self.assertEqual(progress.done, 6)
            self.assertEqual(progress.remaining, 0)

            # check deactivate flag
            cron, progress = cron._add_progress()
            cron._commit_progress(1, deactivate=True)
            self.assertEqual(progress.done, 1)
            self.assertEqual(progress.deactivate, True)
            cron._commit_progress(1)
            self.assertEqual(progress.done, 2)
            self.assertEqual(progress.deactivate, True)

    def test_cron_deactivate(self):
        def mocked_run(self):
            self.env["ir.cron"]._commit_progress(
                processed=1, remaining=0, deactivate=True
            )

        self.cron._trigger()
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.actions.server"], "run", mocked_run),
            self.registry.cursor() as cr,
        ):
            self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr))

        self.env.invalidate_all()
        self.assertFalse(self.cron.active)

    def test_cron_deactivate_production_shape(self):
        """A healthy cron requesting its own deactivation must be deactivated.

        For a cron that never failed (``failure_count == 0``,
        ``first_failure_date is None``, ``active is True``),
        ``_update_failure_count`` recomputes those same values on success, so
        its skip-write optimization sees "no change". The deactivation must
        therefore ride on ``job["deactivate"]``, separate from the row
        snapshot, or the UPDATE is silently dropped. The ``read(load=None)``
        dicts formerly used here (NULL -> ``False``, not ``None``) always
        compared unequal and masked the bug.
        """

        def mocked_run(self):
            self.env["ir.cron"]._commit_progress(
                processed=1, remaining=0, deactivate=True
            )

        self.cron._trigger()
        self.env.flush_all()
        with (
            self.enter_registry_test_mode(),
            patch.object(self.registry["ir.actions.server"], "run", mocked_run),
            self.registry.cursor() as cr,
        ):
            job = self._acquire_job(cr)
            # Pin the production shape of a job without failure history.
            self.assertEqual(job["failure_count"], 0)
            self.assertIsNone(
                job["first_failure_date"],
                "NULL must surface as None, as dictfetchone yields it",
            )
            self.assertTrue(job["active"])
            self.registry["ir.cron"]._process_job(cr, job)

        # Assert against the row itself, not the ORM cache.
        self.env.cr.execute("SELECT active FROM ir_cron WHERE id = %s", [self.cron.id])
        self.assertFalse(
            self.env.cr.fetchone()[0],
            "the deactivation requested via _commit_progress(deactivate=True) "
            "must reach the database",
        )

    def test_gc_cron_triggers_uses_transaction_clock(self):
        # The GC cutoff must come from the transaction clock (cr.now(), the
        # clock that stamps `call_at`), not the process wall clock. Only the
        # transaction clock is advanced past the retention window while the
        # frozen wall clock stays put: the row must be collected.
        self.cron.active = False
        trigger = self.env["ir.cron.trigger"].create(
            {"cron_id": self.cron.id, "call_at": fields.Datetime.now()}
        )
        self.env.flush_all()
        db_future = trigger.call_at + TRIGGER_RETENTION_PERIOD + timedelta(days=1)
        self.patch(self.env.cr, "now", lambda: db_future)
        self.env["ir.cron.trigger"]._gc_cron_triggers()
        self.assertFalse(
            trigger.exists(),
            "GC must follow the transaction clock, not the process wall clock",
        )

    def test_gc_cron_progress_uses_transaction_clock(self):
        # Same discriminator as test_gc_cron_triggers_uses_transaction_clock,
        # for the progress GC (cutoff compared against `create_date`).
        progress = self.env["ir.cron.progress"].create(
            [{"cron_id": self.cron.id, "remaining": 0, "done": 0}]
        )
        self.env.flush_all()
        db_future = progress.create_date + PROGRESS_RETENTION_PERIOD + timedelta(days=1)
        self.patch(self.env.cr, "now", lambda: db_future)
        self.env["ir.cron.progress"]._gc_cron_progress()
        self.assertFalse(
            progress.exists(),
            "GC must follow the transaction clock, not the process wall clock",
        )


class TestIrCronUser(TransactionCaseWithUserDemo, TestIrCron):
    def test_cron_archived_admin_user(self):
        cron_data = self._get_cron_data(self.env)
        cron_data["user_id"] = self.user_demo.id

        user = self.env["res.users"].browse(cron_data["user_id"])
        user.active = False
        user.group_ids = user.group_ids + self.env.ref("base.group_system")
        cron = self.cron.create(cron_data)

        cron._trigger()
        self.env.flush_all()
        with self.enter_registry_test_mode(), self.registry.cursor() as cr:
            with self.assertLogs(
                "odoo.addons.base.models.ir_cron", level="WARNING"
            ) as log_catcher:
                self.registry["ir.cron"]._process_job(cr, self._acquire_job(cr, cron))
                self.assertEqual(
                    [
                        Like(
                            f"...Forbidden server action '{cron.name}' executed while the user {user.login} is archived..."
                        )
                    ],
                    log_catcher.output,
                )

        self.assertEqual(cron.failure_count, 1, "The cron should have failed once")


@tagged("post_install", "-at_install")
class TestIrCronAcquireLock(BaseCase):
    """Two-connection coverage for the ``FOR NO KEY UPDATE ... SKIP LOCKED``
    lock in :meth:`ir.cron._acquire_one_job` (CRON-T1).

    These need genuinely independent connections (not registry-test-mode
    savepoints, which reuse one cursor and never contend for a row lock), so
    they commit a dedicated cron and clean it up explicitly, mirroring
    ``test_ir_sequence.py``'s ``environment()`` pattern.
    """

    def setUp(self):
        super().setUp()
        self.registry = Registry(common.get_db_name())
        # Commit a dedicated, ready cron so both connections see the row.
        # nextcall in the past makes the readiness WHERE clause (real worker
        # path) match without relying on frozen time.
        with self.registry.cursor() as cr:
            env = odoo.api.Environment(cr, common.ADMIN_USER_ID, {})
            cron = env["ir.cron"].create(
                {
                    "name": f"Audit lock cron {secrets.token_urlsafe(8)}",
                    "state": "code",
                    "code": "",
                    "model_id": env.ref("base.model_res_partner").id,
                    "user_id": env.uid,
                    "active": True,
                    "interval_number": 1,
                    "interval_type": "days",
                    "nextcall": datetime(2000, 1, 1, 0, 0, 0),
                }
            )
            self.cron_id = cron.id
            cr.commit()
        self.addCleanup(self._drop_cron)

    def _drop_cron(self):
        with self.registry.cursor() as cr:
            env = odoo.api.Environment(cr, common.ADMIN_USER_ID, {})
            env["ir.cron"].browse(self.cron_id).unlink()
            cr.commit()

    def test_acquire_one_job_skips_locked_row(self):
        """A second connection skips a cron whose row is locked by the first.

        Connection A acquires and locks the cron via ``_acquire_one_job``
        without committing (``FOR NO KEY UPDATE`` held). B's identical call must
        return ``None`` via ``SKIP LOCKED`` rather than block or return the same
        job — the sole guarantee against two workers running one job.
        """
        IrCronModel = self.registry["ir.cron"]
        with self.registry.cursor() as cr_a, self.registry.cursor() as cr_b:
            # Connection A locks the row (no commit -> lock held).
            job_a = IrCronModel._acquire_one_job(cr_a, self.cron_id)
            self.assertIsNotNone(job_a, "connection A should acquire the ready job")
            self.assertEqual(job_a["id"], self.cron_id)

            # B must be skipped by SKIP LOCKED (no block, no row). A broken lock
            # would return the job; a missing SKIP LOCKED would block to timeout.
            job_b = IrCronModel._acquire_one_job(cr_b, self.cron_id)
            self.assertIsNone(
                job_b,
                "connection B must skip the row locked by connection A",
            )

            # Release both locks; the cron stays committed for cleanup.
            cr_a.rollback()
            cr_b.rollback()

    def test_acquire_one_job_after_release(self):
        """Once the lock holder commits, the row becomes acquirable again.

        Confirms the SKIP LOCKED skip in
        :meth:`test_acquire_one_job_skips_locked_row` is due to the live lock,
        not a permanent condition: after A commits, a fresh connection acquires
        the same still-ready job.
        """
        IrCronModel = self.registry["ir.cron"]
        with self.registry.cursor() as cr_a:
            job_a = IrCronModel._acquire_one_job(cr_a, self.cron_id)
            self.assertIsNotNone(job_a)
            cr_a.commit()  # release the lock

        with self.registry.cursor() as cr_b:
            job_b = IrCronModel._acquire_one_job(cr_b, self.cron_id)
            self.assertIsNotNone(
                job_b,
                "the job must be acquirable again once the lock is released",
            )
            self.assertEqual(job_b["id"], self.cron_id)
            cr_b.rollback()

    def test_write_on_running_cron_raises_usererror(self):
        """Editing a cron whose row is locked by a running worker is refused.

        A holds the ``FOR NO KEY UPDATE`` acquire lock. ``write`` on B takes the
        same lock with ``SKIP LOCKED``; the skipped row surfaces as
        ``LockError``, which ``_lock_for_update_or_raise`` must translate into a
        ``UserError`` before touching the record. Guards the guardrail shared by
        ``write`` and ``_unlink_unless_running``.
        """
        IrCronModel = self.registry["ir.cron"]
        with self.registry.cursor() as cr_a, self.registry.cursor() as cr_b:
            job_a = IrCronModel._acquire_one_job(cr_a, self.cron_id)
            self.assertIsNotNone(job_a, "connection A should hold the lock")

            env_b = odoo.api.Environment(cr_b, common.ADMIN_USER_ID, {})
            with self.assertRaises(UserError) as cm:
                env_b["ir.cron"].browse(self.cron_id).write({"priority": 3})
            # Pin to the lock guardrail, not some incidental UserError.
            self.assertIn("currently being executed", str(cm.exception))

            cr_a.rollback()
            cr_b.rollback()

    def test_unlink_on_running_cron_raises_usererror(self):
        """Deleting a cron whose row is locked by a running worker is refused.

        Same contention as :meth:`test_write_on_running_cron_raises_usererror`
        but through the ``@api.ondelete`` hook ``_unlink_unless_running`` (a
        stronger ``FOR UPDATE`` lock, which also conflicts with A's held
        ``FOR NO KEY UPDATE``).
        """
        IrCronModel = self.registry["ir.cron"]
        with self.registry.cursor() as cr_a, self.registry.cursor() as cr_b:
            job_a = IrCronModel._acquire_one_job(cr_a, self.cron_id)
            self.assertIsNotNone(job_a, "connection A should hold the lock")

            env_b = odoo.api.Environment(cr_b, common.ADMIN_USER_ID, {})
            with self.assertRaises(UserError) as cm:
                env_b["ir.cron"].browse(self.cron_id).unlink()
            self.assertIn("currently being executed", str(cm.exception))

            cr_a.rollback()
            cr_b.rollback()


class TestIrCronClassifyOutcome(BaseCase):
    """Unit tests for the pure per-iteration outcome classifier
    :meth:`IrCron._classify_outcome`, a pure function of
    ``(success, done, remaining)`` needing no database.
    """

    def test_classify_outcome_full_truth_table(self):
        FD = CompletionStatus.FULLY_DONE
        PD = CompletionStatus.PARTIALLY_DONE
        FL = CompletionStatus.FAILED
        # (success, done, remaining) -> expected status (None == keep looping)
        cases = {
            (False, 0, 0): FL,  # failed, nothing committed
            (False, 0, 5): FL,  # failed, only remaining known -> failed
            (False, 3, 0): FL,  # failed, no remaining reported -> failed
            (False, 3, 5): None,  # failed but progressed -> retry
            (True, 0, 0): FD,  # no progress API / nothing left
            (True, 3, 0): FD,  # processed all, none remaining
            (True, 0, 5): PD,  # remaining known, none processed this pass
            (True, 3, 5): None,  # processed some, more remain -> loop
        }
        for (success, done, remaining), expected in cases.items():
            with self.subTest(success=success, done=done, remaining=remaining):
                self.assertEqual(
                    IrCron._classify_outcome(
                        success=success, done=done, remaining=remaining
                    ),
                    expected,
                )

    def test_classify_outcome_ignores_magnitude(self):
        # Only truthiness of done/remaining matters, not the exact count.
        self.assertEqual(
            IrCron._classify_outcome(success=True, done=999, remaining=0),
            CompletionStatus.FULLY_DONE,
        )
        self.assertEqual(
            IrCron._classify_outcome(success=True, done=1, remaining=1),
            IrCron._classify_outcome(success=True, done=1000, remaining=1000),
        )


class TestIrCronComputeNextCall(TransactionCase):
    """Unit tests for the DST-aware ``nextcall`` advancement
    (:meth:`IrCron._compute_next_call`): keep the same wall-clock hour across
    DST.
    """

    def _rec(self, tz):
        return self.env["ir.cron"].with_context(tz=tz)

    def test_utc_daily_plain_advance(self):
        rec = self._rec("UTC")
        nextcall = IrCron._compute_next_call(
            rec, datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 3, 12, 0), "days", 1
        )
        self.assertEqual(nextcall, datetime(2026, 1, 4, 0, 0))

    def test_daily_keeps_wall_clock_hour_across_spring_forward(self):
        # 2026-03-08 02:00 EST -> 03:00 EDT (US spring forward).
        # A 07:00-local daily job is 12:00 UTC before, 11:00 UTC after.
        rec = self._rec("America/New_York")
        nextcall = IrCron._compute_next_call(
            rec,
            datetime(2026, 3, 7, 12, 0),  # Sat 07:00 EST
            datetime(2026, 3, 9, 6, 0),  # Mon after the transition
            "days",
            1,
        )
        self.assertEqual(nextcall, datetime(2026, 3, 9, 11, 0))
        local = fields.Datetime.context_timestamp(rec, nextcall)
        self.assertEqual(local.hour, 7, "local wall-clock hour must be preserved")

    def test_daily_keeps_wall_clock_hour_across_fall_back(self):
        # 2026-11-01 02:00 EDT -> 01:00 EST (US fall back).
        rec = self._rec("America/New_York")
        nextcall = IrCron._compute_next_call(
            rec,
            datetime(2026, 10, 31, 11, 0),  # Sat 07:00 EDT (UTC-4)
            datetime(2026, 11, 2, 6, 0),  # Mon after the transition
            "days",
            1,
        )
        self.assertEqual(nextcall, datetime(2026, 11, 2, 12, 0))  # 07:00 EST (UTC-5)
        local = fields.Datetime.context_timestamp(rec, nextcall)
        self.assertEqual(local.hour, 7, "local wall-clock hour must be preserved")

    def test_result_is_strictly_after_now_for_all_interval_types(self):
        rec = self._rec("Europe/Brussels")
        now = datetime(2026, 6, 15, 12, 0)
        overdue = now - timedelta(days=400)
        for interval_type in ("minutes", "hours", "days", "weeks", "months"):
            with self.subTest(interval_type=interval_type):
                nextcall = IrCron._compute_next_call(
                    rec, overdue, now, interval_type, 1
                )
                self.assertGreater(nextcall, now)

    def test_fixed_interval_catchup_matches_stepwise_loop(self):
        # minutes/hours take an arithmetic fast path; it must reproduce the
        # stepwise loop's postcondition exactly: advance by whole intervals
        # from the original nextcall until strictly past now.
        rec = self._rec("America/New_York")
        now = datetime(2026, 6, 15, 12, 0)
        for interval_type, interval_number, overdue in [
            ("minutes", 1, timedelta(hours=3)),
            ("minutes", 7, timedelta(days=2, minutes=3)),
            ("minutes", 30, timedelta(seconds=1)),
            ("hours", 1, timedelta(days=5, minutes=30)),
            ("hours", 6, timedelta(days=1)),
        ]:
            with self.subTest(interval_type=interval_type, n=interval_number):
                nextcall = now - overdue
                expected = nextcall
                step = timedelta(**{interval_type: interval_number})
                while expected <= now:
                    expected += step
                self.assertEqual(
                    IrCron._compute_next_call(
                        rec, nextcall, now, interval_type, interval_number
                    ),
                    expected,
                )

    def test_fixed_interval_boundary_nextcall_equals_now_advances_once(self):
        # The loop advances once when nextcall == now (`<=` guard); the
        # arithmetic path must too.
        rec = self._rec("UTC")
        now = datetime(2026, 6, 15, 12, 0)
        for interval_type in ("minutes", "hours"):
            with self.subTest(interval_type=interval_type):
                self.assertEqual(
                    IrCron._compute_next_call(rec, now, now, interval_type, 5),
                    now + timedelta(**{interval_type: 5}),
                )

    def test_fixed_interval_future_nextcall_unchanged(self):
        # nextcall already strictly past now -> the loop would not run; the
        # arithmetic path must leave it untouched as well.
        rec = self._rec("UTC")
        now = datetime(2026, 6, 15, 12, 0)
        future = now + timedelta(seconds=1)
        self.assertEqual(
            IrCron._compute_next_call(rec, future, now, "minutes", 5), future
        )

    def test_fixed_interval_long_overdue_catchup(self):
        # The motivating case for the fast path: a 1-minute cron 400 days
        # overdue (576,000+ steps for the loop) must land on the next whole
        # interval past now, phase-aligned with the original nextcall.
        rec = self._rec("UTC")
        now = datetime(2026, 6, 15, 12, 0, 30)
        nextcall = now - timedelta(days=400)
        self.assertEqual(
            IrCron._compute_next_call(rec, nextcall, now, "minutes", 1),
            datetime(2026, 6, 15, 12, 1, 30),
        )


class TestIrCronShouldContinue(BaseCase):
    """Unit tests for the pure run-loop continuation predicate
    :meth:`IrCron._should_continue_run`, a pure function of
    ``(status, loop_count, now, end_time)`` needing no database or clock. Its
    rule: loop at least MIN_RUNS_PER_JOB passes AND until the time budget is
    spent, but bail the instant a terminal status is reached.
    """

    def test_terminal_status_stops_immediately(self):
        # Even with no passes done and unlimited budget, a terminal status ends it.
        for status in CompletionStatus:
            with self.subTest(status=status):
                self.assertFalse(
                    IrCron._should_continue_run(
                        status=status, loop_count=0, now=0.0, end_time=1e9
                    )
                )

    def test_under_min_runs_continues_even_with_no_time_left(self):
        # Time budget already spent (now >= end_time) but below the pass floor.
        self.assertTrue(
            IrCron._should_continue_run(
                status=None, loop_count=MIN_RUNS_PER_JOB - 1, now=100.0, end_time=0.0
            )
        )

    def test_min_runs_reached_and_time_spent_stops(self):
        self.assertFalse(
            IrCron._should_continue_run(
                status=None, loop_count=MIN_RUNS_PER_JOB, now=100.0, end_time=100.0
            )
        )

    def test_min_runs_reached_but_time_left_continues(self):
        # Past the pass floor but still within the time budget -> keep looping.
        self.assertTrue(
            IrCron._should_continue_run(
                status=None,
                loop_count=MIN_RUNS_PER_JOB + 5,
                now=50.0,
                end_time=100.0,
            )
        )


class TestIrCronUpdateFailureCount(TransactionCase, CronMixinCase):
    """Direct tests for :meth:`IrCron._update_failure_count`, the failure-count
    / auto-deactivation bookkeeping. It writes ``ir_cron`` via raw SQL, so each
    case builds a ``job`` dict, invokes it, then re-reads the record.
    """

    def setUp(self):
        super().setUp()
        self.cron = self.env["ir.cron"].create(self._get_cron_data(self.env))

    def _now(self):
        return self.env.cr.now().replace(microsecond=0)

    def _job(self, **overrides):
        job = {
            "id": self.cron.id,
            "cron_name": self.cron.cron_name,
            "failure_count": 0,
            "first_failure_date": None,
            "active": True,
        }
        job.update(overrides)
        return job

    def _apply(self, status, **job_overrides):
        self.env["ir.cron"]._update_failure_count(self._job(**job_overrides), status)
        self.cron.invalidate_recordset()

    def test_first_failure_sets_count_and_date(self):
        self._apply(CompletionStatus.FAILED)
        self.assertEqual(self.cron.failure_count, 1)
        self.assertEqual(self.cron.first_failure_date, self._now())
        self.assertTrue(self.cron.active)

    def test_failure_below_count_threshold_increments_only(self):
        old = self._now() - MIN_DELTA_BEFORE_DEACTIVATION - timedelta(days=1)
        # count reaches 3 (< MIN_FAILURE_COUNT_BEFORE_DEACTIVATION): the old date
        # alone must not deactivate.
        self._apply(CompletionStatus.FAILED, failure_count=2, first_failure_date=old)
        self.assertEqual(self.cron.failure_count, 3)
        self.assertTrue(self.cron.active)

    def test_count_met_but_time_window_open_keeps_active(self):
        recent = self._now()  # first failure "now" -> window not elapsed
        self._apply(
            CompletionStatus.FAILED,
            failure_count=MIN_FAILURE_COUNT_BEFORE_DEACTIVATION - 1,
            first_failure_date=recent,
        )
        self.assertEqual(self.cron.failure_count, MIN_FAILURE_COUNT_BEFORE_DEACTIVATION)
        self.assertTrue(self.cron.active, "time window not elapsed -> stay active")

    def test_both_thresholds_met_deactivates_resets_and_notifies(self):
        old = self._now() - MIN_DELTA_BEFORE_DEACTIVATION - timedelta(days=1)
        with patch.object(self.registry["ir.cron"], "_notify_admin") as notify:
            self._apply(
                CompletionStatus.FAILED,
                failure_count=MIN_FAILURE_COUNT_BEFORE_DEACTIVATION - 1,
                first_failure_date=old,
            )
        self.assertFalse(self.cron.active, "both thresholds met -> deactivated")
        self.assertEqual(self.cron.failure_count, 0, "counter reset on deactivation")
        self.assertFalse(self.cron.first_failure_date)
        notify.assert_called_once()

    def test_success_resets_counter_and_date(self):
        old = self._now() - timedelta(days=1)
        for status in (CompletionStatus.FULLY_DONE, CompletionStatus.PARTIALLY_DONE):
            with self.subTest(status=status):
                self.cron.write(
                    {"failure_count": 3, "first_failure_date": old, "active": True}
                )
                # Flush the ORM write to the row before _update_failure_count's
                # raw-SQL UPDATE, otherwise the pending ORM value would be flushed
                # on read-back and clobber it.
                self.cron.flush_recordset()
                self._apply(status, failure_count=3, first_failure_date=old)
                self.assertEqual(self.cron.failure_count, 0)
                self.assertFalse(self.cron.first_failure_date)
                self.assertTrue(self.cron.active)


class TestIrCronDbChecks(TransactionCase):
    """Coverage for the per-database guard rails run before any job.

    ``_check_version`` and ``_check_modules_state`` gate whether a database is
    polled at all (``_process_jobs`` skips the DB when they raise).
    """

    def test_check_version_mismatch_raises_bad_version(self):
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET db_version = %s WHERE name = 'base'",
                ["0.0.0.0.0"],
            )
            with self.assertRaises(BadVersionError):
                IrCron._check_version(self.cr)

    def test_check_version_null_raises_bad_module_state(self):
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET db_version = NULL WHERE name = 'base'"
            )
            with self.assertRaises(BadModuleStateError):
                IrCron._check_version(self.cr)

    def test_check_version_missing_row_raises_bad_module_state(self):
        # A wholly absent ``base`` row is a not-ready (module state) signal, not
        # an opaque TypeError from unpacking an empty ``fetchone()``. Hide the row
        # by renaming rather than deleting (FKs reference it by id).
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET name = 'base__hidden' WHERE name = 'base'"
            )
            with self.assertRaises(BadModuleStateError):
                IrCron._check_version(self.cr)

    def test_check_version_match_passes(self):
        # The live test DB is installed at the current base version.
        IrCron._check_version(self.cr)  # must not raise

    def test_check_modules_state_stable_passes(self):
        # No module in a transient ``to ...`` state -> no-op.
        IrCron._check_modules_state(self.cr, jobs=[])  # must not raise

    def test_check_modules_state_transient_no_jobs_raises(self):
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET state = 'to upgrade' WHERE name = 'base'"
            )
            with self.assertRaises(BadModuleStateError):
                IrCron._check_modules_state(self.cr, jobs=[])

    def test_check_modules_state_transient_recent_job_raises(self):
        recent = fields.Datetime.now()
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET state = 'to upgrade' WHERE name = 'base'"
            )
            with self.assertRaises(BadModuleStateError):
                IrCron._check_modules_state(
                    self.cr, jobs=[{"nextcall": recent, "write_date": recent}]
                )

    def test_check_modules_state_transient_stale_job_forces_reset(self):
        # A ready job older than MAX_FAIL_TIME while modules are stuck is taken
        # as a zombie state -> reset_modules_state is forced (mocked here).
        stale = fields.Datetime.now() - MAX_FAIL_TIME - timedelta(hours=1)
        with closing(self.cr.savepoint()):
            self.cr.execute(
                "UPDATE ir_module_module SET state = 'to upgrade' WHERE name = 'base'"
            )
            with patch(
                "odoo.addons.base.models.ir_cron.reset_modules_state"
            ) as reset_mock:
                IrCron._check_modules_state(
                    self.cr, jobs=[{"nextcall": stale, "write_date": stale}]
                )
            reset_mock.assert_called_once()
