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
        with muter:
            with muter:
                self.assertEqual(logger.handlers, [muter])
            self.assertEqual(logger.handlers, [muter])
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
        root.setLevel(logging.INFO)
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
        self.assertEqual(logging.LogRecord.__bases__, base)


if __name__ == "__main__":
    unittest.main()
