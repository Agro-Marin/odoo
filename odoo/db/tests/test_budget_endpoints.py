"""Tier-1 tests for one connection budget per PostgreSQL *server*.

``db_maxconn`` means "physical connections to PostgreSQL", the number an
operator sizes ``max_connections`` against — so the cap belongs to a server, not
to a pool.  Getting that wrong has failed in both directions:

* one budget per *pool* let a worker hold ``2 * db_maxconn`` (128 against a
  stock 100) when both pools reached the same server;
* one budget for *both pools* bounded the sum of two independent servers once a
  replica was configured, so the replica added no concurrency and — verified
  against a live pair — four replica checkouts made the primary refuse.

Keying on the resolved endpoint is what satisfies both at once, so the two
failure modes are pinned here rather than argued about.  The discriminator is
the whole risk: ``test_enable`` and ``dev_mode=replica`` deliberately point the
read-only pool at the *primary*, and treating "a replica is configured" as
"a second server exists" would hand them two budgets against one machine — the
exact overshoot the shared budget was introduced to remove.

These import ``odoo.db``'s package module, so they exercise the real
``_get_pool`` wiring rather than a stand-in.
"""

import unittest
from unittest.mock import patch

import odoo.db as D
from odoo.db.budget import ConnectionBudget


class _BudgetCase(unittest.TestCase):
    """Each test gets a clean process-wide pool/budget state."""

    def setUp(self):
        self._saved = (D._Pool, D._Pool_readonly, dict(D._budgets))
        D._Pool = D._Pool_readonly = None
        D._budgets.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        D._Pool, D._Pool_readonly, budgets = self._saved
        D._budgets.clear()
        D._budgets.update(budgets)

    def _config(self, **overrides):
        base = {
            "db_host": "",
            "db_port": None,
            "db_user": "",
            "db_password": "",
            "db_sslmode": "prefer",
            "db_replica_host": None,
            "db_replica_port": None,
            "db_replica_user": None,
            "db_replica_password": None,
            "db_replica_sslmode": None,
            "db_maxconn": 64,
            "db_maxconn_replica": None,
            "db_maxconn_gevent": None,
            "db_app_name": "odoo",
        }
        base.update(overrides)
        return patch.dict(D.tools.config.options, base)


class TestOneBudgetPerServer(_BudgetCase):
    def test_no_replica_means_one_shared_budget(self):
        with self._config():
            self.assertIs(D._budget_for(False), D._budget_for(True))

    def test_a_distinct_replica_gets_its_own_budget(self):
        with self._config(db_replica_host="replica.example"):
            self.assertIsNot(D._budget_for(False), D._budget_for(True))

    def test_a_replica_on_the_same_host_but_another_port_is_distinct(self):
        with self._config(
            db_host="pg.example", db_replica_host="pg.example", db_replica_port=5433
        ):
            self.assertIsNot(D._budget_for(False), D._budget_for(True))

    def test_a_replica_pointed_back_at_the_primary_shares_its_budget(self):
        """Someone may set db_replica_host to the primary to exercise readonly
        routes; that is one server and must stay one budget."""
        with self._config(db_host="pg.example", db_replica_host="pg.example"):
            self.assertIs(D._budget_for(False), D._budget_for(True))

    def test_asking_twice_returns_the_same_object(self):
        with self._config(db_replica_host="replica.example"):
            self.assertIs(D._budget_for(True), D._budget_for(True))
            self.assertEqual(len(D._budgets), 1)


class TestTheOvershootCannotComeBack(_BudgetCase):
    """The regression a wrong discriminator would reintroduce."""

    def _ceiling_across_pools(self):
        rw, ro = D._budget_for(False), D._budget_for(True)
        seen = {id(rw): rw, id(ro): ro}
        return sum(b.maxconn for b in seen.values())

    def test_one_server_is_capped_at_db_maxconn_not_double(self):
        with self._config(db_maxconn=64):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_test_enable_does_not_split_the_primary_budget(self):
        """``test_enable`` makes the registry open a readonly connection while
        leaving ``db_replica_host`` unset, so the endpoint must stay the
        primary's; this guards the resolution, not the discriminator."""
        with self._config(db_maxconn=64, test_enable=True):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_dev_mode_replica_does_not_split_the_primary_budget(self):
        with self._config(db_maxconn=64, dev_mode=["replica"]):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_a_replica_pointed_at_the_primary_is_still_one_server_worth(self):
        """The overshoot itself: treating "a replica is configured" as "a second
        server exists" hands one machine ``2 * db_maxconn``."""
        with self._config(
            db_maxconn=64, db_host="pg.example", db_replica_host="pg.example"
        ):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_two_servers_are_capped_at_db_maxconn_each(self):
        with self._config(db_maxconn=64, db_replica_host="replica.example"):
            self.assertEqual(self._ceiling_across_pools(), 128)


class TestReplicaSizing(_BudgetCase):
    def test_the_replica_defaults_to_db_maxconn(self):
        with self._config(db_maxconn=64, db_replica_host="replica.example"):
            self.assertEqual(D._budget_for(True).maxconn, 64)

    def test_db_maxconn_replica_sizes_the_replica_alone(self):
        with self._config(
            db_maxconn=64, db_maxconn_replica=16, db_replica_host="replica.example"
        ):
            self.assertEqual(D._budget_for(True).maxconn, 16)
            self.assertEqual(D._budget_for(False).maxconn, 64)

    def test_it_is_ignored_when_the_replica_is_the_primary(self):
        """A separate ceiling for a server that is the same server is meaningless,
        and honouring it would silently shrink or split the primary's budget."""
        with self._config(db_maxconn=64, db_maxconn_replica=16):
            self.assertIs(D._budget_for(False), D._budget_for(True))
            self.assertEqual(D._budget_for(True).maxconn, 64)


class TestPermitsAreNoLongerShared(_BudgetCase):
    def test_replica_checkouts_do_not_consume_primary_permits(self):
        """The coupling this change removes: a slow replica held permits the
        primary needed, so replica degradation starved primary traffic."""
        with self._config(db_maxconn=2, db_replica_host="replica.example"):
            primary, replica = D._budget_for(False), D._budget_for(True)
            self.assertTrue(replica.acquire(0))
            self.assertTrue(replica.acquire(0))
            self.assertEqual(replica.available, 0)
            self.assertEqual(
                primary.available, 2, "the primary must be untouched by the replica"
            )
            self.assertTrue(primary.acquire(0))
            primary.release()
            replica.release()
            replica.release()

    def test_a_shared_endpoint_still_shares_permits(self):
        with self._config(db_maxconn=2):
            primary, readonly = D._budget_for(False), D._budget_for(True)
            self.assertTrue(readonly.acquire(0))
            self.assertEqual(primary.available, 1, "one server, one pool of permits")
            readonly.release()


class TestBudgetIdentity(_BudgetCase):
    def test_the_budget_handed_to_a_pool_is_the_endpoint_budget(self):
        with self._config(db_replica_host="replica.example"):
            rw, ro = D._get_pool(False), D._get_pool(True)
            self.addCleanup(rw.close_all)
            self.addCleanup(ro.close_all)
            self.assertIs(rw._budget, D._budget_for(False))
            self.assertIs(ro._budget, D._budget_for(True))
            self.assertIsNot(rw._budget, ro._budget)

    def test_each_budget_is_a_real_ConnectionBudget(self):
        with self._config(db_replica_host="replica.example"):
            for readonly in (False, True):
                self.assertIsInstance(D._budget_for(readonly), ConnectionBudget)


class TestBudgetAcquireTimeout(unittest.TestCase):
    """``acquire`` must accept a non-finite timeout — the deadline-less direct
    borrow path hands it ``float("inf")``, and ``BoundedSemaphore.acquire``
    raises ``OverflowError`` on it as soon as the semaphore has to wait, i.e.
    exactly and only when the budget is saturated."""

    def test_inf_timeout_waits_instead_of_overflowing(self):
        import threading

        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        releaser = threading.Timer(0.05, budget.release)
        releaser.start()
        try:
            # Saturated, so this must actually wait: before the fix this
            # raised OverflowError out of the semaphore's deadline arithmetic.
            self.assertTrue(budget.acquire(float("inf")))
        finally:
            releaser.cancel()
            budget.release()
        self.assertEqual(budget.exhausted, 0)

    def test_finite_timeout_still_expires(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        try:
            self.assertFalse(budget.acquire(0.01))
        finally:
            budget.release()
        self.assertEqual(budget.exhausted, 1)


if __name__ == "__main__":
    unittest.main()
