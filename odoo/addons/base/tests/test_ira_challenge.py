"""Regression locks for the 2026-06-15 ir_attachment review follow-up.

These started as adversarial probes of the review's claims; the run was the
arbiter. Two claims held and were fixed here; one was refuted and is pinned so
it cannot be "re-fixed" by mistake.

- C1 (FIXED): create() now runs the comodel/field access check BEFORE the
      content pipeline (SHA-1 / _index / image autoresize), matching write()'s
      documented fail-fast. An unauthorized create must do no content work.
- C2 (REFUTED, pinned): search() shows NO order divergence between su and
      non-su, bounded or unbounded. search_fetch normalizes ``order or
      self._order`` (search.py:173), so _fetch_accessible_ids always receives a
      truthy order; the (res_model, id) batching order only runs for
      search_count, where order is immaterial. The first draft of this test
      asserted the OPPOSITE and failed.
- C3 (FIXED): create() computes the mimetype once; _postprocess_contents reuses
      the value _check_contents already resolved instead of re-sniffing it.
"""

import base64
import gc
import logging
import os
import tracemalloc
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

_logger = logging.getLogger(__name__)


class TestIrAttachmentChallenge(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        # ir.cron is writable only by base.group_system; user_demo
        # (group_user + partner_manager) cannot touch it -> a clean
        # "inaccessible comodel" for the access-check probes.
        self.cron = self.env["ir.cron"].sudo().search([], limit=1)
        self.assertTrue(self.cron, "need at least one ir.cron record")

    # ---- C1: create() fail-fasts like write() --------------------------
    def test_c1_create_fastfails_before_content_processing(self):
        """An unauthorized create rejects BEFORE any content work."""
        calls = []
        orig_check = IrAttachment._check_contents
        orig_datas = IrAttachment._get_datas_related_values

        def spy_check(model, values):
            calls.append("check_contents")
            return orig_check(model, values)

        def spy_datas(model, data, mimetype, backend=None):
            calls.append("datas_related")  # SHA-1 + _index live here
            return orig_datas(model, data, mimetype, backend)

        Demo = self.Attachment.with_user(self.user_demo)
        with (
            patch.object(IrAttachment, "_check_contents", spy_check),
            patch.object(IrAttachment, "_get_datas_related_values", spy_datas),
            self.assertRaises(AccessError),
        ):
            Demo.create(
                {
                    "name": "c1.txt",
                    "raw": b"some indexable text content " * 50,
                    "mimetype": "text/plain",
                    "res_model": "ir.cron",
                    "res_id": self.cron.id,
                }
            )
        self.assertEqual(
            calls, [], "create must reject before running the content pipeline"
        )

    def test_c1_write_fastfails_before_content_processing(self):
        """Symmetry: write() also rejects before any content work."""
        att = self.Attachment.sudo().create(
            {
                "name": "c1w.txt",
                "raw": b"orig",
                "mimetype": "text/plain",
                "res_model": "ir.cron",
                "res_id": self.cron.id,
            }
        )
        calls = []
        orig_check = IrAttachment._check_contents

        def spy_check(model, values):
            calls.append("check_contents")
            return orig_check(model, values)

        demo_att = att.with_user(self.user_demo)
        with (
            patch.object(IrAttachment, "_check_contents", spy_check),
            self.assertRaises(AccessError),
        ):
            demo_att.write({"raw": b"new content"})
        self.assertEqual(calls, [], "write must reject before running _check_contents")

    def test_c1_authorized_create_still_processes_content(self):
        """Guard the fix: an ALLOWED create still runs the content pipeline."""
        att = self.Attachment.with_user(self.user_demo).create(
            {"name": "c1ok.txt", "raw": b"hello world", "mimetype": "text/plain"}
        )
        self.assertEqual(att.raw, b"hello world")
        self.assertTrue(att.checksum, "checksum derived from content")
        self.assertEqual(att.file_size, len(b"hello world"))

    # ---- C2: search ordering is consistent (REFUTES the review claim) --
    def test_c2_search_order_is_consistent_su_and_nonsu(self):
        """search() shows NO order divergence — su/non-su, bounded/unbounded."""
        partner = self.env["res.partner"].sudo().create({"name": "C2 Partner"})
        made = []
        for i in range(6):
            vals = {"name": f"C2ORD-{i}", "raw": b"x", "public": True}
            if i % 2:  # interleave so id-order != res_model-order
                vals.update(res_model="res.partner", res_id=partner.id)
            made.append(self.Attachment.sudo().create(vals).id)
        domain = [("name", "=like", "C2ORD-%")]
        id_desc = sorted(made, reverse=True)

        admin = self.env.ref("base.user_admin")  # is_system, NOT su
        variants = {
            "sudo": self.Attachment.sudo(),
            "demo": self.Attachment.with_user(self.user_demo),
            "admin": self.Attachment.with_user(admin),
        }
        for label, model in variants.items():
            self.assertEqual(model.search(domain).ids, id_desc, f"{label} unbounded")
            self.assertEqual(
                model.search(domain, limit=6).ids, id_desc, f"{label} bounded"
            )

        # the res_model-batched branch IS reached by a bounded search_count,
        # but only the COUNT is observable there (order is immaterial)
        Demo = variants["demo"]
        self.assertEqual(Demo.search_count(domain), 6)
        self.assertEqual(Demo.search_count(domain, limit=4), 4)

    # ---- A1: batch-create memory is bounded (architectural) ------------
    def _measure_create_peak(self, vals_list):
        gc.collect()
        tracemalloc.start()
        try:
            self.Attachment.create(vals_list)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return peak

    def test_a1_batch_create_memory_is_bounded(self):
        """Streaming the payloads to storage keeps peak well under O(total).

        Measured before the fix: the 'raw' path was already flat (0.01x batch
        size — checksum_raw_map referenced the caller's bytes), but the base64
        'datas' path decoded a fresh copy of every row and buffered them all
        (1.01x). create() now writes each payload to the file backend in-loop
        and releases it, so neither path scales with the batch total.
        """
        n, size = 8, 2 * 1024 * 1024
        total = n * size
        base = os.urandom(size)
        raw_peak = self._measure_create_peak(
            [
                {
                    "name": f"raw-{i}.bin",
                    "raw": base + i.to_bytes(4, "big"),
                    "mimetype": "application/octet-stream",
                }
                for i in range(n)
            ]
        )
        datas_peak = self._measure_create_peak(
            [
                {
                    "name": f"d-{i}.bin",
                    "datas": base64.b64encode(base + (1000 + i).to_bytes(4, "big")),
                    "mimetype": "application/octet-stream",
                }
                for i in range(n)
            ]
        )
        _logger.info(
            "MEM total=%d raw_peak=%.2fx datas_peak=%.2fx",
            total,
            raw_peak / total,
            datas_peak / total,
        )
        # both paths must stay well under "all payloads resident at once"
        self.assertLess(raw_peak, total * 0.5, "raw path must not buffer the batch")
        self.assertLess(datas_peak, total * 0.5, "datas path must stream, not buffer")

    # ---- C3: mimetype computed once ------------------------------------
    def test_c3_create_computes_mimetype_once(self):
        """_postprocess_contents reuses the mimetype _check_contents resolved."""
        calls = []
        orig = IrAttachment._mimetype_from_values

        def spy(model, values):
            calls.append(1)
            return orig(model, values)

        with (
            patch.object(IrAttachment, "_mimetype_from_values", spy),
            mute_logger("odoo.addons.base.models.ir_attachment"),
        ):
            self.Attachment.sudo().create(
                {"name": "c3.png", "raw": b"x", "mimetype": "image/png"}
            )
        self.assertEqual(
            sum(calls), 1, "_mimetype_from_values must run once per create vals"
        )
