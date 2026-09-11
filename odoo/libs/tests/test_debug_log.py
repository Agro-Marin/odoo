import logging
import unittest

from odoo.libs.debug_log import (
    _DISABLED_SPAN,
    CHANNELS,
    ROOT,
    DebugLog,
    debug_scope,
    format_event,
)


class _FakeCursor:
    def __init__(self) -> None:
        self.sql_log_count = 0


class TestDebugScope(unittest.TestCase):
    def test_addon_layer_segment_is_dropped(self):
        self.assertEqual(
            debug_scope("odoo.addons.base.models.ir_attachment"), "base.ir_attachment"
        )
        self.assertEqual(
            debug_scope("odoo.addons.base.wizards.base_module_update"),
            "base.base_module_update",
        )
        self.assertEqual(
            debug_scope("odoo.addons.base.models.assetsbundle.bundle"),
            "base.assetsbundle.bundle",
        )

    def test_core_keeps_its_package_path(self):
        self.assertEqual(debug_scope("odoo.orm.models.base"), "orm.models.base")
        self.assertEqual(debug_scope("odoo.modules.loading"), "modules.loading")

    def test_foreign_module_is_left_alone(self):
        self.assertEqual(debug_scope("somepkg.thing"), "somepkg.thing")


class TestFormatEvent(unittest.TestCase):
    def test_plain_values_are_bare_and_spaced_strings_are_quoted(self):
        line = format_event(
            "read", {"model": "res.partner", "name": "a b", "n": 3, "f": 1.23456}
        )
        self.assertEqual(line, "event=read model=res.partner name='a b' n=3 f=1.235")

    def test_empty_string_is_quoted_so_the_key_keeps_a_value(self):
        self.assertEqual(format_event("x", {"s": ""}), "event=x s=''")


class TestDebugLog(unittest.TestCase):
    def setUp(self):
        self.debug = DebugLog("odoo.addons.base.models.ir_attachment")
        self.root = logging.getLogger(ROOT)
        self.saved_level = self.root.level
        self.root.setLevel(logging.NOTSET)
        for channel in CHANNELS:
            logging.getLogger(f"{ROOT}.{channel}").setLevel(logging.NOTSET)

    def tearDown(self):
        self.root.setLevel(self.saved_level)

    def test_loggers_are_named_root_channel_scope(self):
        self.assertEqual(self.debug.scope, "base.ir_attachment")
        for channel in CHANNELS:
            logger = getattr(self.debug, channel).logger
            self.assertEqual(logger.name, f"{ROOT}.{channel}.base.ir_attachment")

    def test_line_channel_emits_only_when_enabled(self):
        logging.getLogger(f"{ROOT}.logic").setLevel(logging.INFO)
        with self.assertNoLogs(self.root, logging.DEBUG):
            self.debug.logic("noop", a=1)
        logging.getLogger(f"{ROOT}.logic").setLevel(logging.NOTSET)
        with self.assertLogs(f"{ROOT}.logic", logging.DEBUG) as captured:
            self.debug.logic("hit", model="res.partner", ids=[1, 2])
        self.assertEqual(
            captured.output,
            [
                f"DEBUG:{ROOT}.logic.base.ir_attachment:event=hit model=res.partner ids=[1, 2]"
            ],
        )

    def test_perf_span_is_a_shared_noop_when_disabled(self):
        self.root.setLevel(logging.INFO)
        span = self.debug.perf("read", cr=_FakeCursor())
        self.assertIs(span, _DISABLED_SPAN)
        with span as inner:
            inner.set(rows=1)

    def test_perf_span_reports_ms_queries_and_extra_fields(self):
        cr = _FakeCursor()
        with self.assertLogs(f"{ROOT}.perf", logging.DEBUG) as captured:
            with self.debug.perf("read", cr=cr, model="res.partner") as span:
                cr.sql_log_count += 3
                span.set(rows=7)
        (line,) = captured.output
        self.assertIn("event=read model=res.partner rows=7 ms=", line)
        self.assertTrue(line.endswith(" queries=3"))

    def test_perf_count_is_a_single_line(self):
        with self.assertLogs(f"{ROOT}.perf", logging.DEBUG) as captured:
            self.debug.perf.count("cache", hits=3, misses=1)
        self.assertEqual(
            captured.output,
            [f"DEBUG:{ROOT}.perf.base.ir_attachment:event=cache hits=3 misses=1"],
        )

    def test_perf_span_names_the_exception_and_reraises(self):
        with self.assertLogs(f"{ROOT}.perf", logging.DEBUG) as captured:
            with self.assertRaises(ValueError):
                with self.debug.perf("boom"):
                    raise ValueError("x")
        (line,) = captured.output
        self.assertTrue(line.endswith(" error=ValueError"))
        self.assertNotIn("queries=", line)

    def test_channel_enabled_reflects_the_logger_level(self):
        self.root.setLevel(logging.INFO)
        self.assertFalse(self.debug.pipeline.enabled)
        logging.getLogger(f"{ROOT}.pipeline").setLevel(logging.DEBUG)
        self.assertTrue(self.debug.pipeline.enabled)
        logging.getLogger(f"{ROOT}.pipeline").setLevel(logging.NOTSET)
