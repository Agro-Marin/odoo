import gc
import unittest

from odoo.libs.gc import _timing_gc_callback, disabling_gc, gc_info, gc_set_timing


class TestDisablingGc(unittest.TestCase):
    def setUp(self):
        was_enabled = gc.isenabled()
        gc.enable()
        self.addCleanup(gc.enable if was_enabled else gc.disable)

    def test_reenables_after_exception(self):
        with self.assertRaises(RuntimeError):
            with disabling_gc() as active:
                self.assertTrue(active)
                self.assertFalse(gc.isenabled())
                raise RuntimeError("boom")
        self.assertTrue(gc.isenabled())

    def test_reenables_after_normal_exit(self):
        with disabling_gc():
            self.assertFalse(gc.isenabled())
        self.assertTrue(gc.isenabled())

    def test_noop_when_already_disabled(self):
        gc.disable()
        try:
            with disabling_gc() as active:
                self.assertFalse(active)
                self.assertFalse(gc.isenabled())
        finally:
            gc.enable()


class TestGcSetTiming(unittest.TestCase):
    def tearDown(self):
        gc_set_timing(enable=False)

    def test_enable_registers_callback_once(self):
        self.assertNotIn(_timing_gc_callback, gc.callbacks)
        gc_set_timing(enable=True)
        self.assertIn(_timing_gc_callback, gc.callbacks)
        gc_set_timing(enable=True)
        self.assertEqual(gc.callbacks.count(_timing_gc_callback), 1)

    def test_disable_unregisters_callback(self):
        gc_set_timing(enable=True)
        gc_set_timing(enable=False)
        self.assertNotIn(_timing_gc_callback, gc.callbacks)

    def test_disable_when_not_registered_is_a_noop(self):
        gc_set_timing(enable=False)
        self.assertNotIn(_timing_gc_callback, gc.callbacks)


class TestGcInfo(unittest.TestCase):
    def tearDown(self):
        gc_set_timing(enable=False)

    def test_shape_without_timing_enabled(self):
        info = gc_info()
        self.assertEqual(info["time"], ())
        self.assertIsInstance(info["cumulative_time"], float)
        self.assertEqual(len(info["count"]), len(gc.get_stats()))
        thresholds, limits = info["thresholds"]
        # live counters (gc.get_count() ticks with every intervening
        # allocation), so only shape/type is stable across the two calls.
        self.assertEqual(len(thresholds), len(gc.get_count()))
        self.assertEqual(limits, gc.get_threshold())

    def test_shape_with_timing_enabled_and_zero_collections(self):
        gc_set_timing(enable=True)
        info = gc_info()
        self.assertIsInstance(info["time"], list)
        self.assertEqual(len(info["time"]), len(gc.get_stats()))
        for entry in info["time"]:
            self.assertIn("avg_time_ms", entry)
            self.assertIn("time_ms", entry)
            self.assertIn("share", entry)
            # no collections have run yet since enabling: avg_time_ms must not
            # divide by zero.
            self.assertEqual(entry["avg_time_ms"], 0.0)

    def test_share_after_a_real_collection(self):
        gc_set_timing(enable=True)
        gc.collect()
        info = gc_info()
        self.assertGreaterEqual(sum(entry["share"] for entry in info["time"]), 0.0)


if __name__ == "__main__":
    unittest.main()
