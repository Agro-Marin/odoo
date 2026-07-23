"""Regression tests for ``odoo.libs.logging`` context managers."""

import logging
import unittest

from odoo.libs.logging import lower_logging, mute_logger


class TestMuteLogger(unittest.TestCase):
    def test_reentrant_instance_restores_fully(self):
        name = "odoo.test.mute.reentrant"
        logger = logging.getLogger(name)
        original_handlers = logger.handlers
        original_propagate = logger.propagate
        muter = mute_logger(name)
        # reuse the same instance nested (as a recursive decorator would)
        with muter:
            with muter:
                self.assertEqual(logger.handlers, [muter])
            # still muted inside the outer block
            self.assertEqual(logger.handlers, [muter])
        # fully restored after the outer block
        self.assertIs(logger.handlers, original_handlers)
        self.assertEqual(logger.propagate, original_propagate)


class TestLowerLogging(unittest.TestCase):
    def test_lowers_level_without_class_surgery(self):
        base = logging.LogRecord.__bases__
        records = []
        sink = logging.Handler()
        sink.emit = records.append
        root = logging.getLogger()
        old_level = root.level
        root.setLevel(logging.INFO)  # so the lowered record clears the threshold
        root.addHandler(sink)
        try:
            with lower_logging(logging.WARNING, logging.INFO) as ll:
                logging.getLogger("odoo.test.lower").error("boom")
            self.assertTrue(ll.had_error_log)
            self.assertTrue(records)
            self.assertEqual(records[-1].levelno, logging.INFO)
            self.assertTrue(records[-1].levelname.startswith("_"))
        finally:
            root.removeHandler(sink)
            root.setLevel(old_level)
        # the LogRecord class hierarchy must be untouched (no __bases__ graft)
        self.assertEqual(logging.LogRecord.__bases__, base)


if __name__ == "__main__":
    unittest.main()
