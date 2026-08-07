from threading import Barrier, Thread

from odoo.orm.runtime.registry import _CACHES_BY_KEY
from odoo.tests.common import BaseCase, TransactionCase, get_cache_key_counter, tagged
from odoo.tools.cache import get_cache_size


def _cleared_by(*cache_names: str) -> str:
    cleared = {sub for name in cache_names for sub in _CACHES_BY_KEY[name]}
    return repr(sorted(cleared))


class TestCacheSize(BaseCase):
    def test_get_cache_size_traverses_instance_dict(self):

        class Holder:
            pass

        holder = Holder()
        holder.payload = b"x" * 1_000_000

        self.assertGreater(get_cache_size(holder), 1_000_000)


@tagged("-at_install", "post_install")
class TestOrmCache(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.registry.registry_invalidated:
            msg = "Registry should not be invalidated when starting this test"
            raise AssertionError(msg)
        if cls.registry.cache_invalidated:
            msg = "Cache should not be invalidated when starting this test"
            raise AssertionError(msg)

        cls._signal_changes_patcher.stop()
        cls._retry = False

        import odoo.tools.cache as _cache_mod

        cls.addClassCleanup(
            setattr, _cache_mod, "_TX_STATS_ENABLED", _cache_mod._TX_STATS_ENABLED
        )
        _cache_mod._TX_STATS_ENABLED = True

    def test_ormcache(self):
        IMD = self.env["ir.model.data"]
        XMLID = "base.group_no_one"

        cache, key, counter = get_cache_key_counter(IMD._xmlid_lookup, XMLID)
        hit = counter.hit
        miss = counter.miss
        tx_hit = counter.tx_hit
        tx_miss = counter.tx_miss

        self.env.registry.clear_cache()
        self.assertNotIn(key, cache)

        self.env.ref(XMLID)
        self.assertEqual(counter.hit, hit)
        self.assertEqual(counter.miss, miss + 1)
        self.assertEqual(counter.tx_hit, tx_hit)
        self.assertEqual(counter.tx_miss, tx_miss + 1)
        self.assertIn(key, cache)

        self.env.ref(XMLID)
        self.assertEqual(counter.hit, hit + 1)
        self.assertEqual(counter.miss, miss + 1)
        self.assertEqual(counter.tx_hit, tx_hit)
        self.assertEqual(counter.tx_miss, tx_miss + 1)
        self.assertIn(key, cache)

        self.env.ref(XMLID)
        self.assertEqual(counter.hit, hit + 2)
        self.assertEqual(counter.miss, miss + 1)
        self.assertEqual(counter.tx_hit, tx_hit)
        self.assertEqual(counter.tx_miss, tx_miss + 1)
        self.assertIn(key, cache)

    def test_invalidation(self):
        self.assertEqual(self.env.registry.cache_invalidated, set())
        self.env.registry.clear_cache()
        self.env.registry.clear_cache("templates")
        self.assertEqual(self.env.registry.cache_invalidated, {"default", "templates"})
        self.env.registry.reset_changes()
        self.assertEqual(self.env.registry.cache_invalidated, set())
        self.env.registry.clear_cache("assets")
        self.assertEqual(self.env.registry.cache_invalidated, {"assets"})
        self.env.registry.reset_changes()
        self.assertEqual(self.env.registry.cache_invalidated, set())

    def test_invalidation_thread_local(self):

        caches = ["default", "templates", "assets"]
        nb_treads = len(caches)

        sync_clear_cache = Barrier(nb_treads, timeout=5)
        sync_assert_equal = Barrier(nb_treads, timeout=5)
        sync_reset = Barrier(nb_treads, timeout=5)

        operations = []

        def run(cache):
            self.assertEqual(self.env.registry.cache_invalidated, set())

            self.env.registry.clear_cache(cache)
            operations.append("clear_cache")
            sync_clear_cache.wait()

            self.assertEqual(self.env.registry.cache_invalidated, {cache})
            operations.append("assert_contains")
            sync_assert_equal.wait()

            self.env.registry.reset_changes()
            operations.append("reset_changes")
            sync_reset.wait()

            self.assertEqual(self.env.registry.cache_invalidated, set())
            operations.append("assert_empty")

        threads = [Thread(target=run, args=(cache,)) for cache in caches]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(
            operations,
            ["clear_cache"] * nb_treads
            + ["assert_contains"] * nb_treads
            + ["reset_changes"] * nb_treads
            + ["assert_empty"] * nb_treads,
        )

    def test_signaling_01_single(self):
        self.assertFalse(self._registry_patched)
        self.registry.cache_invalidated.clear()
        registry = self.registry
        old_sequences = dict(registry.cache_sequences)
        with self.assertLogs("odoo.registry") as logs:
            registry.cache_invalidated.add("assets")
            self.assertEqual(registry.cache_invalidated, {"assets"})
            registry.signal_changes()
            self.assertFalse(registry.cache_invalidated)

        self.assertEqual(
            logs.output,
            [
                "INFO:odoo.registry:Caches invalidated, signaling through the database: ['assets']"
            ],
        )

        for key, value in old_sequences.items():
            if key == "assets":
                self.assertEqual(
                    value + 1,
                    registry.cache_sequences[key],
                    "Assets cache sequence should have changed",
                )
            else:
                self.assertEqual(
                    value,
                    registry.cache_sequences[key],
                    "other registry sequence shouldn't have changed",
                )

        with self.assertNoLogs(None, None):
            registry.check_signaling()

        registry.cache_sequences.update(old_sequences)

        with self.assertLogs("odoo.registry") as logs:
            registry.check_signaling()
        self.assertEqual(
            logs.output,
            [
                "INFO:odoo.registry:Invalidating caches after database signaling: "
                + _cleared_by("assets")
            ],
        )

    def test_signaling_01_multiple(self):
        self.assertFalse(self._registry_patched)
        self.registry.cache_invalidated.clear()
        registry = self.registry
        old_sequences = dict(registry.cache_sequences)
        with self.assertLogs("odoo.registry") as logs:
            registry.cache_invalidated.add("assets")
            registry.cache_invalidated.add("default")
            self.assertEqual(registry.cache_invalidated, {"assets", "default"})
            registry.signal_changes()
            self.assertFalse(registry.cache_invalidated)

        self.assertEqual(
            logs.output,
            [
                "INFO:odoo.registry:Caches invalidated, signaling through the database: ['assets', 'default']",
            ],
        )

        for key, value in old_sequences.items():
            if key in ("assets", "default"):
                self.assertEqual(
                    value + 1,
                    registry.cache_sequences[key],
                    "Assets and default cache sequence should have changed",
                )
            else:
                self.assertEqual(
                    value,
                    registry.cache_sequences[key],
                    "other registry sequence shouldn't have changed",
                )

        with self.assertNoLogs(None, None):
            registry.check_signaling()

        registry.cache_sequences.update(old_sequences)

        with self.assertLogs("odoo.registry") as logs:
            registry.check_signaling()
        self.assertEqual(
            logs.output,
            [
                "INFO:odoo.registry:Invalidating caches after database signaling: "
                + _cleared_by("assets", "default")
            ],
        )

    def test_signaling_gc(self):
        cr = self.env.cr
        cr.execute("SELECT last_value FROM orm_signaling_registry_id_seq")
        sequence_start = cr.fetchone()[0]

        def assertSignalCount(expected_count, expected_max_id, message):
            cr.execute("SELECT count(*), max(id) FROM orm_signaling_registry")
            count, max_id = cr.fetchone()
            self.assertEqual(expected_count, count, message)
            self.assertEqual(expected_max_id, max_id - sequence_start, message)

        cr.execute("DELETE FROM orm_signaling_registry")

        for _ in range(7):
            cr.execute(
                "INSERT INTO orm_signaling_registry (date) VALUES (NOW() - interval '2 hours')"
            )

        cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")

        assertSignalCount(8, 8, "8 signals were inserted")
        self.env["ir.autovacuum"]._gc_orm_signaling()
        assertSignalCount(8, 8, "less than 10 signals, no deletion")

        for _ in range(5):
            cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")

        assertSignalCount(13, 13, "5 more signals were inserted")
        self.env["ir.autovacuum"]._gc_orm_signaling()
        assertSignalCount(10, 13, "more than 10 signals, some should have been deleted")

        for _ in range(7):
            cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")

        assertSignalCount(17, 20, "7 more signals were inserted")
        self.env["ir.autovacuum"]._gc_orm_signaling()
        assertSignalCount(13, 20, "Keeping the 13 signals having less than one hour")

        cr.execute(f"SELECT setval('orm_signaling_registry_id_seq', {sequence_start})")
