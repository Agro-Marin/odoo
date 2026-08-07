import contextlib
import itertools
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase, new_test_user, tagged

from odoo.addons.base.models import ir_autovacuum

_IR_AUTOVACUUM_LOGGER = "odoo.addons.base.models.ir_autovacuum"


@tagged("post_install", "-at_install")
class TestAutovacuumDispatcher(TransactionCase):
    def test_run_vacuum_requires_cron_id_in_context(self):
        autovacuum = self.env["ir.autovacuum"]
        self.assertTrue(autovacuum.env.is_admin())
        self.assertFalse(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()

    def test_run_vacuum_requires_admin(self):
        user = new_test_user(self.env, login="av_plain_user")
        autovacuum = self.env["ir.autovacuum"].with_user(user).with_context(cron_id=1)
        self.assertFalse(autovacuum.env.is_admin())
        self.assertTrue(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()


@tagged("post_install", "-at_install")
class TestAutovacuumTimeBudget(TransactionCase):
    @staticmethod
    def _getmembers_stub(methods):

        def fake_getmembers(cls, predicate=None):
            if getattr(cls, "_name", None) == "ir.autovacuum":
                return methods
            return []

        return fake_getmembers

    def _run(self, methods, fake_time=None):
        autovacuum = self.env["ir.autovacuum"].with_context(cron_id=1)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    ir_autovacuum,
                    "inspect",
                    SimpleNamespace(getmembers=self._getmembers_stub(methods)),
                )
            )
            stack.enter_context(
                patch.object(
                    type(self.env["ir.cron"]),
                    "_commit_progress",
                    lambda cron, *args, **kwargs: float("inf"),
                )
            )
            if fake_time is not None:
                stack.enter_context(patch.object(ir_autovacuum, "time", fake_time))
            autovacuum._run_vacuum_cleaner()

    def test_within_budget_requeues_remaining_work(self):
        calls = []

        def fake_gc(model):
            calls.append(model._name)
            return (1, len(calls) == 1)

        with self.assertNoLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING"):
            self._run([("_gc_fake", fake_gc)])
        self.assertEqual(calls, ["ir.autovacuum", "ir.autovacuum"])

    def test_budget_exceeded_stops_requeueing(self):
        calls = []

        def fake_gc(model):
            calls.append(model._name)
            return (1, 12345)

        ticks = itertools.count(start=0, step=2000)
        fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
        with self.assertLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING") as capture:
            self._run([("_gc_fake", fake_gc)], fake_time=fake_time)
        self.assertEqual(calls, ["ir.autovacuum"])
        warning = "\n".join(capture.output)
        self.assertIn("wall-clock budget", warning)
        self.assertIn("ir.autovacuum._gc_fake", warning)
        self.assertIn("12345", warning)

    def test_budget_does_not_skip_first_pass(self):
        calls = []

        def fake_gc_a(model):
            calls.append("a")
            return (1, True)

        def fake_gc_b(model):
            calls.append("b")
            return (1, False)

        ticks = itertools.count(start=0, step=2000)
        fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
        with self.assertLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING"):
            self._run(
                [("_gc_fake_a", fake_gc_a), ("_gc_fake_b", fake_gc_b)],
                fake_time=fake_time,
            )
        self.assertEqual(sorted(calls), ["a", "b"])
        self.assertEqual(len(calls), 2)
