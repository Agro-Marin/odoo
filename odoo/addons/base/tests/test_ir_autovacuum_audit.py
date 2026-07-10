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
    """Regression coverage for the ir.autovacuum dispatcher guard (audit AV-T1).

    ``_run_vacuum_cleaner`` requires ``is_admin()`` AND a ``cron_id`` in context,
    else it raises ``AccessDenied``. The failure-isolation contract is not
    covered here (it needs the dispatch loop to commit between methods, forbidden
    in a TransactionCase; already covered in test_orm).
    """

    def test_run_vacuum_requires_cron_id_in_context(self):
        """As superuser/admin but without cron_id in context -> AccessDenied."""
        autovacuum = self.env["ir.autovacuum"]
        self.assertTrue(autovacuum.env.is_admin())
        self.assertFalse(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()

    def test_run_vacuum_requires_admin(self):
        """A non-admin user, even with cron_id in context, is rejected."""
        user = new_test_user(self.env, login="av_plain_user")
        autovacuum = self.env["ir.autovacuum"].with_user(user).with_context(cron_id=1)
        self.assertFalse(autovacuum.env.is_admin())
        self.assertTrue(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()


@tagged("post_install", "-at_install")
class TestAutovacuumTimeBudget(TransactionCase):
    """Regression coverage for the ``_run_vacuum_cleaner`` wall-clock budget.

    A method reporting remaining work is re-enqueued only while within
    ``MAX_VACUUM_RUNTIME``; past the budget the backlog is deferred to the next
    run (with a warning). First-pass methods are never skipped.

    The loop is driven with fake ``@api.autovacuum`` methods
    (``inspect.getmembers`` stubbed inside the ir_autovacuum module), so no real
    ``_gc_*`` runs. ``ir.cron._commit_progress`` is stubbed too: without a cron
    progress record in context it would fall through to a raw ``cr.commit()``,
    forbidden on the shared TransactionCase cursor.
    """

    @staticmethod
    def _getmembers_stub(methods):
        """Return an ``inspect.getmembers`` stand-in exposing ``methods``
        (``(name, func)`` pairs) on ir.autovacuum only, nothing elsewhere."""

        def fake_getmembers(cls, predicate=None):
            if getattr(cls, "_name", None) == "ir.autovacuum":
                return methods
            return []

        return fake_getmembers

    def _run(self, methods, fake_time=None):
        """Run the dispatcher with ``methods`` (``(name, func)`` pairs) as the
        only autovacuum methods, optionally under a stubbed ``time`` namespace.
        Swaps only the ir_autovacuum module's ``inspect``/``time`` references
        plus ``ir.cron._commit_progress`` (see the class docstring)."""
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
        """Under the budget, a truthy ``remaining`` re-enqueues the method."""
        calls = []

        def fake_gc(model):
            calls.append(model._name)
            # more work on the first pass, done on the second
            return (1, len(calls) == 1)

        with self.assertNoLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING"):
            self._run([("_gc_fake", fake_gc)])
        self.assertEqual(calls, ["ir.autovacuum", "ir.autovacuum"])

    def test_budget_exceeded_stops_requeueing(self):
        """Past the budget, remaining work is deferred (not re-enqueued) and
        the deferral is logged as a warning naming the method."""
        calls = []

        def fake_gc(model):
            calls.append(model._name)
            return (1, 12345)  # always reports remaining work

        # The dispatcher reads the clock at run start, per-method start, the
        # re-enqueue check and the per-method duration log: +2000s per read
        # exceeds the 3600s budget at the first re-enqueue check.
        ticks = itertools.count(start=0, step=2000)
        fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
        with self.assertLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING") as capture:
            self._run([("_gc_fake", fake_gc)], fake_time=fake_time)
        # Ran exactly once: the backlog was deferred instead of re-enqueued.
        self.assertEqual(calls, ["ir.autovacuum"])
        warning = "\n".join(capture.output)
        self.assertIn("wall-clock budget", warning)
        self.assertIn("ir.autovacuum._gc_fake", warning)
        self.assertIn("12345", warning)

    def test_budget_does_not_skip_first_pass(self):
        """Methods still awaiting their first pass run even after the budget
        is exhausted -- only RE-enqueueing stops."""
        calls = []

        def fake_gc_a(model):
            calls.append("a")
            return (1, True)

        def fake_gc_b(model):
            calls.append("b")
            return (1, False)

        # Budget already blown when the first re-enqueue check happens, yet
        # both first passes must run.
        ticks = itertools.count(start=0, step=2000)
        fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
        with self.assertLogs(_IR_AUTOVACUUM_LOGGER, level="WARNING"):
            self._run(
                [("_gc_fake_a", fake_gc_a), ("_gc_fake_b", fake_gc_b)],
                fake_time=fake_time,
            )
        self.assertEqual(sorted(calls), ["a", "b"])
        self.assertEqual(len(calls), 2)
