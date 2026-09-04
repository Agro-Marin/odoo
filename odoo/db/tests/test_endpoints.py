import threading
import time
import unittest
import unittest.mock

import odoo.db as D
from odoo import tools
from odoo.db.budget import ConnectionBudget
from odoo.db.endpoints import EndpointRegistry


class _BudgetCase(unittest.TestCase):
    def setUp(self):
        self.reg = EndpointRegistry()
        patcher = unittest.mock.patch.object(D, "registry", self.reg)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        return tools.config.patch(**base)


class TestOneBudgetPerServer(_BudgetCase):
    def test_no_replica_means_one_shared_budget(self):
        with self._config():
            self.assertIs(
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )

    def test_a_distinct_replica_gets_its_own_budget(self):
        with self._config(db_replica_host="replica.example"):
            self.assertIsNot(
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )

    def test_a_replica_on_the_same_host_but_another_port_is_distinct(self):
        with self._config(
            db_host="pg.example", db_replica_host="pg.example", db_replica_port=5433
        ):
            self.assertIsNot(
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )

    def test_a_replica_pointed_back_at_the_primary_shares_its_budget(self):
        with self._config(db_host="pg.example", db_replica_host="pg.example"):
            self.assertIs(
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )

    def test_asking_twice_returns_the_same_object(self):
        with self._config(db_replica_host="replica.example"):
            self.assertIs(
                self.reg.get_budget_for_readonly(True),
                self.reg.get_budget_for_readonly(True),
            )
            self.assertEqual(len(self.reg._budgets), 1)

    def test_a_uri_to_the_configured_server_shares_its_budget(self):
        with self._config(db_host="pg.example", db_port=5432):
            configured = self.reg.get_budget_for_readonly(False)
            for uri in (
                "postgresql://pg.example/db",
                "postgresql://pg.example/db?user=someone",
                "postgresql://pg.example:5432/db",
            ):
                with self.subTest(uri=uri):
                    _, info = D.get_connection_info_for_database(uri)
                    self.assertIs(
                        self.reg.get_budget_at_endpoint(D.get_endpoint_key(info)),
                        configured,
                        "a URI that omits ?port= names the same server; filing "
                        "it apart hands one server two budgets and lets a "
                        "worker hold 2 * db_maxconn backends against it",
                    )

    def test_a_uri_that_omits_the_host_defaults_to_the_configured_one(self):
        with self._config(db_host="pg.example", db_port=5432):
            _, info = D.get_connection_info_for_database("postgresql:///db")
            self.assertEqual(
                D.get_endpoint_key(info),
                self.reg.get_endpoint_for_readonly(False),
                "a URI spells only what it spells; the rest has to default the "
                "way the configured endpoint does, or the same server is filed "
                "twice and gets two budgets",
            )

    def test_the_uri_defaults_come_from_the_config_not_the_environment(self):
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(D.get_endpoint_key)))
        reads = {
            ast.unparse(n.func)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertNotIn(
            "os.environ.get",
            reads,
            "db_host/db_port are registered with env_name PGHOST/PGPORT, so "
            "PoolSettings.from_config has already folded the environment in; "
            "reading it again here is a second source of truth that misses a "
            "db_host set in the conf file",
        )
        self.assertNotIn("tools", ast.unparse(tree))
        self.assertIn("settings.host", ast.unparse(tree))
        self.assertIn("settings.port", ast.unparse(tree))

    def test_a_uri_to_another_server_still_gets_its_own_budget(self):
        with self._config(db_host="pg.example", db_port=5432):
            _, info = D.get_connection_info_for_database(
                "postgresql://other.example/db"
            )
            self.assertIsNot(
                self.reg.get_budget_at_endpoint(D.get_endpoint_key(info)),
                self.reg.get_budget_for_readonly(False),
            )


class TestTheOvershootCannotComeBack(_BudgetCase):
    def _ceiling_across_pools(self):
        rw, ro = (
            self.reg.get_budget_for_readonly(False),
            self.reg.get_budget_for_readonly(True),
        )
        seen = {id(rw): rw, id(ro): ro}
        return sum(b.maxconn for b in seen.values())

    def test_one_server_is_capped_at_db_maxconn_not_double(self):
        with self._config(db_maxconn=64):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_test_enable_does_not_split_the_primary_budget(self):
        with self._config(db_maxconn=64, test_enable=True):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_dev_mode_replica_does_not_split_the_primary_budget(self):
        with self._config(db_maxconn=64, dev_mode=["replica"]):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_a_replica_pointed_at_the_primary_is_still_one_server_worth(self):
        with self._config(
            db_maxconn=64, db_host="pg.example", db_replica_host="pg.example"
        ):
            self.assertEqual(self._ceiling_across_pools(), 64)

    def test_two_servers_are_capped_at_db_maxconn_each(self):
        with self._config(db_maxconn=64, db_replica_host="replica.example"):
            self.assertEqual(self._ceiling_across_pools(), 128)

    def test_a_uri_to_the_primary_cannot_double_the_ceiling(self):
        with self._config(db_maxconn=64, db_host="pg.example", db_port=5432):
            _, info = D.get_connection_info_for_database("postgresql://pg.example/db")
            budgets = {
                id(b): b
                for b in (
                    self.reg.get_budget_for_readonly(False),
                    self.reg.get_budget_for_readonly(True),
                    self.reg.get_budget_at_endpoint(D.get_endpoint_key(info)),
                )
            }
            self.assertEqual(
                sum(b.maxconn for b in budgets.values()),
                64,
                "--log-db is the one allow_uri=True caller and it aims at a "
                "URI; when that URI names the configured server it must draw "
                "on the configured server's permits",
            )

    def test_a_uri_to_the_primary_shares_its_pool(self):
        with self._config(db_host="pg.example", db_port=5432):
            configured = self.reg.get_pool_for_readonly(False)
            self.addCleanup(configured.close_all)
            _, info = D.get_connection_info_for_database("postgresql://pg.example/db")
            self.assertIs(
                self.reg.get_pool_at_endpoint(D.get_endpoint_key(info), False),
                configured,
            )


class TestOnePoolRegistry(_BudgetCase):
    def test_every_fan_out_snapshots_under_the_lock(self):
        import inspect

        for name in ("is_pooled", "close_db", "close_all", "drain_db", "drain_all"):
            with self.subTest(function=name):
                src = inspect.getsource(getattr(EndpointRegistry, name))
                self.assertIn(
                    "self.get_all_pools()",
                    src,
                    "iterating the registry bare while another thread creates "
                    "a pool raises RuntimeError: dictionary changed size "
                    "during iteration",
                )
        for name in ("get_all_pools", "get_health"):
            with self.subTest(function=name):
                self.assertIn(
                    "with self._lock:",
                    inspect.getsource(getattr(EndpointRegistry, name)),
                    "the snapshot itself must be taken under the lock",
                )

    def test_there_is_one_registry_and_one_factory(self):
        for gone in ("_uri_pools", "_uri_budgets", "_Pool", "_Pool_readonly"):
            with self.subTest(name=gone):
                self.assertFalse(
                    hasattr(D, gone),
                    "the URI pools were a second registry with a second budget "
                    "map, a second factory and a second copy of the fan-out",
                )

    def test_a_pool_at_another_endpoint_is_labelled_by_that_endpoint(self):
        with self._config(db_host="pg.example", db_port=5432):
            self.reg.get_pool_for_readonly(False)
            _, info = D.get_connection_info_for_database(
                "postgresql://elsewhere.example:5433/db"
            )
            other = self.reg.get_pool_at_endpoint(D.get_endpoint_key(info), False)
            self.addCleanup(other.close_all)
            health = D.get_pool_health()
            self.assertIn(
                "uri:elsewhere.example:5433:read_write",
                health,
                "get_pool_health's keys become the `pool=` label on every metric "
                "odoo_pool_* exports, so a second server has to name itself "
                "rather than overwrite read_write",
            )
            self.assertIsNotNone(health["read_write"])

    def test_a_uri_is_refused_unless_the_caller_allows_it(self):
        with self._config():
            with self.assertRaises(ValueError):
                D.db_connect("postgresql://elsewhere.example/db")
            conn = D.db_connect("postgresql://elsewhere.example/db", allow_uri=True)
            self.addCleanup(self.reg._pools.clear)
            self.assertEqual(
                conn.dbname,
                "db",
                "with allow_uri the URI's path is the database name",
            )

    def test_pool_health_still_names_the_configured_endpoints(self):
        with self._config():
            rw = self.reg.get_pool_for_readonly(False)
            self.addCleanup(rw.close_all)
            health = D.get_pool_health()
            self.assertIsNotNone(health["read_write"])
            self.assertIn("read_only", health)


class TestReplicaSizing(_BudgetCase):
    def test_the_replica_defaults_to_db_maxconn(self):
        with self._config(db_maxconn=64, db_replica_host="replica.example"):
            self.assertEqual(self.reg.get_budget_for_readonly(True).maxconn, 64)

    def test_db_maxconn_replica_sizes_the_replica_alone(self):
        with self._config(
            db_maxconn=64, db_maxconn_replica=16, db_replica_host="replica.example"
        ):
            self.assertEqual(self.reg.get_budget_for_readonly(True).maxconn, 16)
            self.assertEqual(self.reg.get_budget_for_readonly(False).maxconn, 64)

    def test_it_is_ignored_when_the_replica_is_the_primary(self):
        with self._config(db_maxconn=64, db_maxconn_replica=16):
            self.assertIs(
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )
            self.assertEqual(self.reg.get_budget_for_readonly(True).maxconn, 64)


class TestPermitsAreNoLongerShared(_BudgetCase):
    def test_replica_checkouts_do_not_consume_primary_permits(self):
        with self._config(db_maxconn=2, db_replica_host="replica.example"):
            primary, replica = (
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )
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
            primary, readonly = (
                self.reg.get_budget_for_readonly(False),
                self.reg.get_budget_for_readonly(True),
            )
            self.assertTrue(readonly.acquire(0))
            self.assertEqual(primary.available, 1, "one server, one pool of permits")
            readonly.release()


class TestBudgetIdentity(_BudgetCase):
    def test_the_budget_handed_to_a_pool_is_the_endpoint_budget(self):
        with self._config(db_replica_host="replica.example"):
            rw, ro = (
                self.reg.get_pool_for_readonly(False),
                self.reg.get_pool_for_readonly(True),
            )
            self.addCleanup(rw.close_all)
            self.addCleanup(ro.close_all)
            self.assertIs(rw._budget, self.reg.get_budget_for_readonly(False))
            self.assertIs(ro._budget, self.reg.get_budget_for_readonly(True))
            self.assertIsNot(rw._budget, ro._budget)

    def test_each_budget_is_a_real_ConnectionBudget(self):
        with self._config(db_replica_host="replica.example"):
            for readonly in (False, True):
                self.assertIsInstance(
                    self.reg.get_budget_for_readonly(readonly), ConnectionBudget
                )


class TestBudgetAcquireTimeout(unittest.TestCase):
    def test_inf_timeout_waits_instead_of_overflowing(self):
        import threading

        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        releaser = threading.Timer(0.05, budget.release)
        releaser.start()
        try:
            self.assertTrue(budget.acquire(float("inf")))
        finally:
            releaser.cancel()
            budget.release()
        self.assertEqual(budget.exhausted_count, 0)

    def test_finite_timeout_still_expires(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        try:
            self.assertFalse(budget.acquire(0.01))
        finally:
            budget.release()
        self.assertEqual(budget.exhausted_count, 1)


if __name__ == "__main__":
    unittest.main()


class TestTheCapHoldsUnderRealContention(unittest.TestCase):
    MAXCONN = 4
    THREADS = 40
    ROUNDS = 25
    HOLD = 0.002

    def test_permits_out_never_exceed_maxconn(self):
        budget = ConnectionBudget(self.MAXCONN)
        lock = threading.Lock()
        state = {"cur": 0, "peak": 0}
        failures: list[str] = []

        def worker():
            for _ in range(self.ROUNDS):
                if not budget.acquire(30.0):
                    failures.append("acquire timed out with permits available")
                    return
                with lock:
                    state["cur"] += 1
                    state["peak"] = max(state["peak"], state["cur"])
                    if state["cur"] > self.MAXCONN:
                        failures.append(f"{state['cur']} permits out")
                time.sleep(self.HOLD)
                with lock:
                    state["cur"] -= 1
                budget.release()

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        self.assertEqual(failures, [], "the cap was breached or a waiter starved")
        self.assertEqual(
            state["peak"],
            self.MAXCONN,
            "the run never saturated, so it proves nothing about the cap",
        )
        self.assertEqual(budget.in_use, 0, "every permit was returned")
        self.assertEqual(budget.available, self.MAXCONN)

    def test_a_release_wakes_a_waiter(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(1.0))
        served: list[int] = []

        def waiter(i):
            if budget.acquire(20.0):
                served.append(i)
                budget.release()

        threads = [threading.Thread(target=waiter, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        budget.release()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(len(served), 8, f"a waiter was never woken: {sorted(served)}")

    def test_a_zero_timeout_still_takes_a_free_permit(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        self.assertFalse(budget.acquire(0))
        self.assertFalse(budget.acquire(-5))
        budget.release()
        self.assertTrue(budget.acquire(0))
