import gc
import unittest

from odoo.libs.gc import disabling_gc


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


if __name__ == "__main__":
    unittest.main()
