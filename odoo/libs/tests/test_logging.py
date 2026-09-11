import logging
import threading
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

    def test_overlapping_mutes_restore_on_the_last_exit_whatever_the_order(self):
        name = "odoo.test.mute.overlap"
        logger = logging.getLogger(name)
        original_handlers = logger.handlers
        first, second = mute_logger(name), mute_logger(name)
        first.__enter__()
        second.__enter__()
        first.__exit__()
        self.assertFalse(logger.propagate)
        self.assertEqual(logger.handlers, [first])
        second.__exit__()
        self.assertIs(logger.handlers, original_handlers)
        self.assertTrue(logger.propagate)

    def test_a_mute_held_by_one_thread_does_not_block_another(self):
        name = "odoo.test.mute.threads"
        logger = logging.getLogger(name)
        original_handlers = logger.handlers
        inside, release = threading.Event(), threading.Event()

        def hold():
            with mute_logger(name):
                inside.set()
                release.wait(10)

        def enter_and_leave():
            with mute_logger(name):
                pass

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            self.assertTrue(inside.wait(10))
            other = threading.Thread(target=enter_and_leave)
            other.start()
            other.join(2)
            self.assertFalse(other.is_alive())
            self.assertFalse(logger.propagate)
        finally:
            release.set()
            holder.join(10)
        self.assertIs(logger.handlers, original_handlers)
        self.assertTrue(logger.propagate)


class TestLowerLogging(unittest.TestCase):
    def test_lowers_level_without_class_surgery(self):
        base = logging.LogRecord.__bases__
        records: list[logging.LogRecord] = []
        sink = logging.Handler()
        sink.emit = records.append  # type: ignore[method-assign,assignment]
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
