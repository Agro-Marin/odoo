"""`_OrmProfile.report` derives the phase tail from the marks.

Twenty-six ORM call sites used to spell that tail out by hand -- a format
string naming each phase and one `prof.ms(a, b)` per phase -- and nothing tied
the names in the string to the names of the marks. `write()` had already
drifted: its last phase was marked ``validate1`` and labelled ``inverse=``.
"""

import logging
import unittest

from odoo.libs.profiling import OrmProfiler, _OrmProfile


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def messages(self):
        return [r.getMessage() for r in self.records]


class _ProfileTestCase(unittest.TestCase):
    def _logger(self, level=logging.DEBUG):
        logger = logging.getLogger(f"odoo.test.profile.{id(self)}.{level}")
        logger.handlers.clear()
        logger.setLevel(level)
        logger.propagate = False
        capture = _Capture()
        logger.addHandler(capture)
        return logger, capture


class TestReportDerivesThePhases(_ProfileTestCase):
    def test_each_phase_is_named_by_the_mark_that_ends_it(self):
        logger, capture = self._logger()
        prof = _OrmProfile(logger)
        prof.mark("acl")
        prof.mark("prep")
        prof.stop("validate")
        prof.report(logger, "create %s: %d records", "res.partner", 3)
        [message] = capture.messages
        self.assertRegex(
            message,
            r"^\[\d+\.\d+ ms\] create res\.partner: 3 records"
            r" \| acl=\d+\.\d+ prep=\d+\.\d+ validate=\d+\.\d+$",
        )

    def test_the_final_phase_takes_the_name_stop_was_given(self):
        logger, capture = self._logger()
        prof = _OrmProfile(logger)
        prof.mark("search")
        prof.stop("fetch")
        prof.report(logger, "search_fetch %s", "res.partner")
        self.assertIn("| search=", capture.messages[0])
        self.assertIn(" fetch=", capture.messages[0])
        self.assertNotIn("end=", capture.messages[0])

    def test_no_marks_means_no_phase_tail(self):
        logger, capture = self._logger()
        prof = _OrmProfile(logger)
        prof.stop()
        prof.report(logger, "_write_multi %s: %d records", "res.partner", 4)
        [message] = capture.messages
        self.assertNotIn("|", message)
        self.assertRegex(
            message, r"^\[\d+\.\d+ ms\] _write_multi res\.partner: 4 records$"
        )

    def test_a_message_with_no_arguments_still_works(self):
        logger, capture = self._logger()
        prof = _OrmProfile(logger)
        prof.mark("acl")
        prof.stop("query")
        prof.report(logger, "_search res.partner")
        self.assertRegex(
            capture.messages[0],
            r"^\[\d+\.\d+ ms\] _search res\.partner \| acl=\d+\.\d+ query=\d+\.\d+$",
        )

    def test_below_debug_it_emits_nothing_and_evaluates_no_format(self):
        logger, capture = self._logger(logging.INFO)
        prof = _OrmProfile(logger)
        prof.stop()
        prof.report(logger, "create %s", "res.partner")
        self.assertEqual(capture.messages, [])

    def test_elapsed_follows_the_named_final_mark(self):
        logger, _capture = self._logger()
        prof = _OrmProfile(logger)
        prof.mark("acl")
        prof.stop("validate")
        self.assertGreaterEqual(prof.elapsed, 0.0)
        self.assertEqual(
            prof.elapsed,
            prof._marks["validate"] - prof._marks["start"],
            "elapsed must measure to the final mark, whatever it is called",
        )

    def test_marks_are_not_taken_when_logging_is_off(self):
        logger, _capture = self._logger(logging.INFO)
        prof = _OrmProfile(logger)
        prof.mark("acl")
        self.assertNotIn("acl", prof._marks)


class TestTheProfilerRecordsByName(_ProfileTestCase):
    def test_record_takes_the_operation_as_data(self):
        profiler = OrmProfiler()
        profiler.record("create", "res.partner", 3, 0.5)
        profiler.record("create", "res.partner", 2, 0.25)
        profiler.record("write", "res.users", 1, 0.125)
        stats = profiler._data[("create", "res.partner")]
        self.assertEqual((stats.count, stats.records, stats.time), (2, 5, 0.75))
        self.assertIn(("write", "res.users"), profiler._data)

    def test_no_per_operation_methods_remain(self):
        leftovers = [name for name in dir(OrmProfiler) if name.startswith("record_")]
        self.assertEqual(
            leftovers,
            [],
            "eight methods that each spelled their operation twice were "
            "collapsed into record(); a new one is a regression",
        )


if __name__ == "__main__":
    unittest.main()
