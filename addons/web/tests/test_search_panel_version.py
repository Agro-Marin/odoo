"""Tests for the ``__version`` content-hash stamp on cached read endpoints.

Background: ``rpc_cache.js`` ``payloadChanged`` prefers a cheap version
compare over deep ``jsonEqual`` when the server response carries
``__version``.  The ``versioned``/``versioned_envelope`` decorators
(``odoo/tools/cache_version.py``) opt a method into this contract.

Currently covered:
  - ``search_panel_select_range`` / ``search_panel_select_multi_range``
  - ``web_search_read`` (hot path: every list/kanban refresh)
  - ``web_read_group`` (hot path: every grouped view refresh)

These tests pin:
  1. The decorator stamps a sha256 hex hash on dict returns.
  2. Identical queries produce identical hashes across calls (cache
     stability invariant — without it, the client would always think
     the payload changed).
  3. A change in the underlying records produces a different hash
     (correctness invariant — without it, the client would miss
     genuine changes).
"""

import json

from odoo.exceptions import UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged


@tagged("web_unit", "web_search_panel")
class TestSearchPanelVersion(TransactionCase):
    """Pins the ``__version`` stamp contract on search-panel endpoints."""

    def setUp(self):
        super().setUp()
        # Two partners with parent-child so the panel call returns
        # something non-empty and exercises the values-list path.
        self.parent = self.env["res.partner"].create({
            "name": "Plan-C Parent",
            "is_company": True,
        })
        self.child = self.env["res.partner"].create({
            "name": "Plan-C Child",
            "is_company": False,
            "parent_id": self.parent.id,
        })

    def _call_select_range(self):
        return self.env["res.partner"].search_panel_select_range(
            "parent_id",
            search_domain=[("name", "ilike", "Plan-C")],
            enable_counters=True,
        )

    def test_select_range_returns_version(self):
        result = self._call_select_range()
        self.assertIn("__version", result)
        # sha256 hex digest is 64 chars
        self.assertEqual(len(result["__version"]), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in result["__version"]))

    def test_select_range_same_query_same_version(self):
        v1 = self._call_select_range()["__version"]
        v2 = self._call_select_range()["__version"]
        self.assertEqual(v1, v2, "Identical queries must produce identical version stamps")

    def test_select_range_record_change_changes_version(self):
        v1 = self._call_select_range()["__version"]
        # Rename a record so the panel's `display_name` changes.
        self.parent.name = "Plan-C Parent (renamed)"
        v2 = self._call_select_range()["__version"]
        self.assertNotEqual(v1, v2, "Record mutation must produce a different version stamp")

    def test_select_multi_range_returns_version(self):
        result = self.env["res.partner"].search_panel_select_multi_range(
            "parent_id",
            search_domain=[("name", "ilike", "Plan-C")],
        )
        self.assertIn("__version", result)
        self.assertEqual(len(result["__version"]), 64)

    def test_version_field_does_not_collide_with_response_keys(self):
        # The decorator skips already-stamped dicts so a future endpoint
        # that legitimately uses ``__version`` for application data can opt
        # out by setting it before returning.
        result = self._call_select_range()
        # Real response shape includes 'parent_field' and 'values' (or
        # 'error_msg' on failure).  Asserting on those documents that
        # ``__version`` rides alongside, not in place of, the payload.
        self.assertTrue("values" in result or "error_msg" in result)


@tagged("web_unit", "web_search_panel")
class TestWebSearchReadVersion(TransactionCase):
    """``web_search_read`` is the hot-path cached read used by every
    list/kanban refresh; the ``__version`` stamp lets the client cache
    skip its deep ``jsonEqual`` comparison on stale-while-revalidate
    refreshes (``relational_model.js:377``).
    """

    def setUp(self):
        super().setUp()
        self.partners = self.env["res.partner"].create([
            {"name": "Plan-C WSR A", "is_company": True},
            {"name": "Plan-C WSR B", "is_company": False},
        ])

    def _call(self):
        return self.env["res.partner"].web_search_read(
            [("name", "ilike", "Plan-C WSR")],
            {"display_name": {}, "is_company": {}},
        )

    def test_returns_version(self):
        result = self._call()
        self.assertIn("__version", result)
        self.assertEqual(len(result["__version"]), 64)
        # Sanity: real response shape preserved alongside __version.
        self.assertEqual(result["length"], 2)
        self.assertEqual(len(result["records"]), 2)

    def test_same_query_same_version(self):
        self.assertEqual(self._call()["__version"], self._call()["__version"])

    def test_record_change_changes_version(self):
        v1 = self._call()["__version"]
        self.partners[0].name = "Plan-C WSR A (renamed)"
        v2 = self._call()["__version"]
        self.assertNotEqual(v1, v2)


@tagged("web_unit", "web_search_panel")
class TestSearchPanelUnknownField(TransactionCase):
    """An unknown ``field_name`` must raise a clean ``UserError``, not a raw
    ``KeyError`` bubbling up as a 500 (``self._fields[field_name]``).
    """

    def test_select_range_unknown_field_raises_usererror(self):
        with self.assertRaises(UserError):
            self.env["res.partner"].search_panel_select_range("no_such_field_xyz")

    def test_select_multi_range_unknown_field_raises_usererror(self):
        with self.assertRaises(UserError):
            self.env["res.partner"].search_panel_select_multi_range("no_such_field_xyz")

    def test_known_field_still_works(self):
        # A valid field must not be affected by the guard.
        result = self.env["res.partner"].search_panel_select_range("parent_id")
        self.assertIn("values", result)


@tagged("post_install", "-at_install", "web_http", "web_search_panel")
class TestWebReadEnvelopeVersion(HttpCase):
    """``web_read`` returns a ``list`` and uses the envelope-side channel
    (``@versioned_envelope``) instead of in-payload stamping.  The hash
    rides as a sibling of ``result`` in the JSON-RPC envelope; verify it
    appears in the wire response of an actual ``call_kw`` HTTP round-trip.
    """

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "Plan-C Envelope Partner",
            "is_company": True,
        })

    def _call_web_read(self):
        """POST a real call_kw against /web/dataset/call_kw and decode the envelope."""
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/web/dataset/call_kw/res.partner/web_read",
            data=json.dumps({
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": "res.partner",
                    "method": "web_read",
                    "args": [[self.partner.id]],
                    "kwargs": {"specification": {"display_name": {}, "is_company": {}}},
                },
            }),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_envelope_carries_version_sibling(self):
        envelope = self._call_web_read()
        self.assertIn("version", envelope, "envelope must carry version sibling")
        self.assertEqual(len(envelope["version"]), 64)
        # Verify result is a list (not a dict) — confirming the envelope path
        # is the right vehicle, vs the in-payload @versioned decorator.
        self.assertIsInstance(envelope["result"], list)

    def test_same_query_same_version(self):
        v1 = self._call_web_read()["version"]
        v2 = self._call_web_read()["version"]
        self.assertEqual(v1, v2)

    def test_record_change_changes_version(self):
        v1 = self._call_web_read()["version"]
        self.partner.name = "Plan-C Envelope Partner (renamed)"
        v2 = self._call_web_read()["version"]
        self.assertNotEqual(v1, v2)


@tagged("web_unit", "web_search_panel")
class TestWebReadGroupVersion(TransactionCase):
    """``web_read_group`` is the hot-path cached read used by every
    grouped list / kanban / pivot refresh; ``__version`` lets the
    client cache skip ``jsonEqual`` on stale-while-revalidate.
    """

    def setUp(self):
        super().setUp()
        self.env["res.partner"].create([
            {"name": "Plan-C RG A1", "is_company": True},
            {"name": "Plan-C RG A2", "is_company": True},
            {"name": "Plan-C RG B1", "is_company": False},
        ])

    def _call(self):
        return self.env["res.partner"].web_read_group(
            [("name", "ilike", "Plan-C RG")],
            ["is_company"],
            ["__count"],
        )

    def test_returns_version(self):
        result = self._call()
        self.assertIn("__version", result)
        self.assertEqual(len(result["__version"]), 64)
        # Real shape preserved (web_read_group returns {groups, length}).
        self.assertIn("groups", result)
        self.assertIn("length", result)

    def test_same_query_same_version(self):
        self.assertEqual(self._call()["__version"], self._call()["__version"])

    def test_group_change_changes_version(self):
        v1 = self._call()["__version"]
        # Add a new record so a count flips.
        self.env["res.partner"].create({
            "name": "Plan-C RG A3",
            "is_company": True,
        })
        v2 = self._call()["__version"]
        self.assertNotEqual(v1, v2)
