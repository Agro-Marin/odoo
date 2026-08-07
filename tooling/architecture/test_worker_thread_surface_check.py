#!/usr/bin/env python3
"""Self-test for ``worker_thread_surface_check.py``.

A gate that cannot fail is decoration. These pin the ways this one could lie:

* **Blindness to a real access** — the inline attribute form
  (``threading.current_thread().dbname``) and the reflective form
  (``getattr(threading.current_thread(), "cursor_mode", None)``) must both be
  seen, for every ``WorkerThread`` attribute.
* **The documented boundary** — a *stored/aliased* thread reference
  (``t = threading.current_thread(); t.dbname``) is deliberately NOT flagged;
  a test locks that so the boundary is a decision, not an accident.
* **Over-matching** — a standard ``Thread`` attribute (``.name``, ``.ident``)
  and an attribute of the same name on some *other* object must not count.
* **New coupling fails** — a raw access absent from the baseline must make
  ``--check`` fail; that is the whole purpose.
* **Missing a conversion fails** — a baseline entry nothing produces anymore
  must also fail, so a conversion is committed (exact-ratchet discipline).
* **Protocol-tracking** — the attribute set is the one the live Protocol
  declares, and the committed ``KNOWN_RAW_SURFACE`` matches the real tree, so
  the gate ships green rather than already-red or already-lying.

Run directly or under pytest.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import worker_thread_surface_check as wtsc


def _collect(src: str) -> list[tuple[str, int]]:
    collector = wtsc._WorkerThreadCollector()
    collector.visit(ast.parse(src))
    return collector.hits


class TestCollector(unittest.TestCase):
    def test_sees_inline_attribute_form(self):
        attrs = {
            a
            for a, _ in _collect(
                "threading.current_thread().dbname = db\n"
                "x = threading.current_thread().cursor_mode\n"
                "y = current_thread().uid\n"  # bare import form
            )
        }
        self.assertEqual(attrs, {"dbname", "cursor_mode", "uid"})

    def test_sees_getattr_hasattr_delattr_forms(self):
        attrs = {
            a
            for a, _ in _collect(
                'a = getattr(threading.current_thread(), "dbname", None)\n'
                'b = hasattr(threading.current_thread(), "query_count")\n'
                'delattr(threading.current_thread(), "query_count")\n'
            )
        }
        self.assertEqual(attrs, {"dbname", "query_count"})

    def test_ignores_stored_or_aliased_thread_reference(self):
        # The documented coverage boundary: a reference held for a specific
        # thread's identity is a different concern from reading the current
        # thread's bookkeeping inline, so it is intentionally not flagged.
        hits = _collect(
            "t = threading.current_thread()\n"
            "x = t.dbname\n"
            "self._thread = threading.current_thread()\n"
            "y = self._thread.query_count\n"
        )
        self.assertEqual(hits, [])

    def test_ignores_standard_thread_attributes(self):
        hits = _collect(
            "a = threading.current_thread().name\n"
            "b = threading.current_thread().ident\n"
            'c = getattr(threading.current_thread(), "daemon", False)\n'
        )
        self.assertEqual(hits, [])

    def test_ignores_same_name_attr_on_other_objects(self):
        hits = _collect(
            "a = self.dbname\n"  # not the current thread
            "b = record.env.cr.dbname\n"
            'c = getattr(some_obj, "dbname", None)\n'
        )
        self.assertEqual(hits, [])


class TestProtocolTracking(unittest.TestCase):
    def test_attrs_come_from_the_live_protocol(self):
        # The eight bookkeeping fields the Protocol declares today.
        self.assertEqual(
            wtsc.PROTOCOL_ATTRS,
            frozenset(
                {
                    "dbname",
                    "uid",
                    "url",
                    "query_count",
                    "query_time",
                    "perf_t0",
                    "cursor_mode",
                    "rpc_model_method",
                }
            ),
        )


class TestRatchet(unittest.TestCase):
    def test_new_raw_access_fails_check(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "sample.py"
            tmp.write_text("x = threading.current_thread().dbname\n", encoding="utf-8")
            report = wtsc.check([tmp])
        self.assertFalse(report.ok)
        self.assertTrue(any(attr == "dbname" for _path, attr in report.added))

    def test_missing_baseline_entry_fails_check(self):
        # A baseline pair that the tree no longer produces must surface as
        # `removed`, so a real conversion cannot be silently un-done.
        original = wtsc.KNOWN_RAW_SURFACE
        wtsc.KNOWN_RAW_SURFACE = frozenset({("odoo/gone.py", "dbname")})
        try:
            report = wtsc.check([])  # no files -> no reaches
            self.assertFalse(report.ok)
            self.assertIn(("odoo/gone.py", "dbname"), report.removed)
        finally:
            wtsc.KNOWN_RAW_SURFACE = original


class TestLiveTree(unittest.TestCase):
    def test_committed_baseline_matches_the_real_tree(self):
        report = wtsc.check()
        self.assertTrue(
            report.ok,
            "worker-thread surface drifted from KNOWN_RAW_SURFACE:\n"
            f"  new: {sorted(report.added)}\n  gone: {sorted(report.removed)}",
        )

    def test_core_has_no_inline_raw_accesses(self):
        # The adoption claim: cursor_mode and every sibling attribute is reached
        # through current_worker_thread(), not inline current_thread(), in core.
        report = wtsc.check()
        self.assertEqual([r.pair for r in report.reaches], [])


if __name__ == "__main__":
    unittest.main()
