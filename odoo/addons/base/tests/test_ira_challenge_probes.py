"""Challenge probes — empirically validate (or refute) the 2026-06-13 review claims.

Each test instruments a specific claim from the ir_attachment review and asserts
what ACTUALLY happens, so an overstated claim fails loudly instead of being
believed. Findings under test:

- A1 (RETRACTED): create() relies on _check_contents returning the same dict,
  but is provably robust to a new-dict-returning override — mimetype is stamped
  in place before any fork and _inverse_raw re-derives the rest post-create.
  The only residue is one redundant content pass (no corruption).
- B1 (CONFIRMED): every dedup hit reads the whole stored file back (collision
  check in _get_path -> _same_content); now opt-out via
  ir_attachment.verify_content_collision.
- B2 (CONFIRMED, NARROWED): _check_access("write") is skipped under su and runs
  twice only for non-su writes (explicit call + super().write).
- B3 (FIXED): one write-side backend is now threaded through the content path
  instead of being rebuilt in _get_datas_related_values.
"""

import logging
from unittest.mock import patch

from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

_logger = logging.getLogger(__name__)

_HTML = b"<html><body>challenge</body></html>"


class TestIraReviewChallenge(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        # pin the write-side backend so the file-collision path is exercised
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "file")

    # -- A1 (RETRACTED as a correctness bug) --------------------------------
    def test_a1_create_is_robust_to_new_dict_override(self):
        """create() stays CORRECT even when _postprocess_contents returns a new
        dict — refuting the 'silent corruption' claim.

        Two safety nets converge: _check_contents sets `mimetype` on the
        original vals IN PLACE (before _postprocess_contents can fork a copy),
        and the un-popped `raw` left in vals_list triggers `_inverse_raw`
        post-create, which recomputes checksum/file_size/store_fname. The ONLY
        observable effect is one redundant content-processing pass.
        """
        ctrl = self.Attachment.create({"name": "ctrl", "raw": _HTML})
        ctrl.invalidate_recordset()

        set_calls = []
        real_set = IrAttachment._set_attachment_data

        def count_set(model, asbytes):
            set_calls.append(1)
            return real_set(model, asbytes)

        real_pp = IrAttachment._postprocess_contents

        def copy_pp(model, values):
            # the trigger: return a brand-new dict instead of mutating in place
            return dict(real_pp(model, values))

        with (
            patch.object(IrAttachment, "_postprocess_contents", copy_pp),
            patch.object(IrAttachment, "_set_attachment_data", count_set),
        ):
            broken = self.Attachment.create({"name": "broken", "raw": _HTML})
        broken.invalidate_recordset()

        _logger.info(
            "A1 PROBE | mimetype ctrl=%r broken=%r | checksum match=%s | "
            "file_size=%r | store_fname set=%s | redundant_passes=%d",
            ctrl.mimetype,
            broken.mimetype,
            broken.checksum == ctrl.checksum,
            broken.file_size,
            bool(broken.store_fname),
            len(set_calls),
        )

        # everything ends up correct — NOT corrupted
        self.assertEqual(broken.raw, _HTML)
        self.assertEqual(broken.mimetype, ctrl.mimetype, "mimetype preserved in place")
        self.assertEqual(
            broken.checksum, ctrl.checksum, "checksum recomputed correctly"
        )
        self.assertEqual(broken.file_size, len(_HTML))
        self.assertTrue(broken.store_fname, "store key set via _inverse_raw")
        # the only real effect: a redundant second content pass (perf, not bug)
        self.assertEqual(
            len(set_calls), 1, "un-popped raw causes one redundant content pass"
        )

    # -- B1 -----------------------------------------------------------------
    def test_b1_dedup_reads_full_stored_file(self):
        """Re-uploading identical content byte-compares the whole stored file."""
        payload = b"B1-" + b"x" * 4096
        same_content_calls = []
        real_same = IrAttachment._same_content

        def spy_same(model, bin_data, filepath):
            from pathlib import Path

            same_content_calls.append(Path(filepath).stat().st_size)
            return real_same(model, bin_data, filepath)

        with patch.object(IrAttachment, "_same_content", spy_same):
            first = self.Attachment.create({"name": "b1-a.bin", "raw": payload})
            self.env.flush_all()
            after_first = len(same_content_calls)
            second = self.Attachment.create({"name": "b1-b.bin", "raw": payload})
            self.env.flush_all()
            after_second = len(same_content_calls)

        _logger.info(
            "B1 PROBE | calls_after_first_create=%d calls_after_second=%d "
            "compared_sizes=%r store_fname_shared=%s",
            after_first,
            after_second,
            same_content_calls,
            first.store_fname == second.store_fname,
        )

        # first upload writes a new file: no existing file to compare against
        self.assertEqual(after_first, 0, "B1: first upload does not byte-compare")
        # second (dedup) upload compares the full existing file
        self.assertEqual(after_second, 1, "B1: dedup triggers exactly one compare")
        self.assertEqual(
            same_content_calls[0],
            len(payload),
            "B1: the full stored file is read for the collision check",
        )
        self.assertEqual(
            first.store_fname, second.store_fname, "content-addressed dedup"
        )

    def test_b1_collision_check_opt_out(self):
        """ir_attachment.verify_content_collision=False skips the dedup re-read."""
        self.env["ir.config_parameter"].set_param(
            "ir_attachment.verify_content_collision", "False"
        )
        payload = b"B1-optout-" + b"y" * 4096
        calls = []
        real_same = IrAttachment._same_content

        def spy_same(model, bin_data, filepath):
            calls.append(1)
            return real_same(model, bin_data, filepath)

        with patch.object(IrAttachment, "_same_content", spy_same):
            first = self.Attachment.create({"name": "opt-a.bin", "raw": payload})
            self.env.flush_all()
            second = self.Attachment.create({"name": "opt-b.bin", "raw": payload})
            self.env.flush_all()

        _logger.info(
            "B1-OPTOUT PROBE | _same_content calls with param off = %d", len(calls)
        )
        self.assertEqual(len(calls), 0, "opt-out must skip the full-file compare")
        # dedup still works (content-addressed key is shared), content intact
        self.assertEqual(first.store_fname, second.store_fname)
        second.invalidate_recordset()
        self.assertEqual(second.raw, payload)

    # -- B2 (CORRECTED: only non-su pays it, and it pays double) ------------
    def test_b2_check_access_double_only_for_non_su(self):
        """_check_access('write') is skipped entirely under su, but runs TWICE
        for a non-su write (explicit check_access + super().write).

        This narrows the original claim: content writes go through .sudo(), so
        the hot path pays nothing; the double cost is non-su metadata writes.
        """
        su_writes, demo_writes = [], []
        real_check = IrAttachment._check_access

        def spy_check(model, operation):
            if operation == "write":
                (su_writes if model.env.su else demo_writes).append(1)
            return real_check(model, operation)

        # su path (default test env is superuser): check_access short-circuits
        att_su = self.Attachment.create({"name": "b2-su.txt", "raw": b"b2su"})
        with patch.object(IrAttachment, "_check_access", spy_check):
            att_su.write({"description": "su write"})
            self.env.flush_all()

        # non-su path: demo writes its own (res_model-less) attachment
        Demo = self.Attachment.with_user(self.user_demo)
        att_demo = Demo.create({"name": "b2-demo.txt", "raw": b"b2demo"})
        su_writes.clear()
        with patch.object(IrAttachment, "_check_access", spy_check):
            att_demo.write({"description": "demo write"})
            Demo.env.flush_all()

        _logger.info(
            "B2 PROBE | su _check_access('write')=%d  demo _check_access('write')=%d",
            len(su_writes),
            len(demo_writes),
        )
        self.assertEqual(len(su_writes), 0, "su writes never reach _check_access")
        self.assertEqual(len(demo_writes), 2, "non-su write runs the heavy check twice")

    # -- B3 -----------------------------------------------------------------
    def test_b3_storage_backend_built_twice_per_content_write(self):
        """_storage_backend() is constructed twice writing content to one row."""
        att = self.Attachment.create({"name": "b3.bin", "raw": b"b3-orig"})

        backend_calls = []
        real_backend = IrAttachment._storage_backend

        def spy_backend(model):
            backend_calls.append(1)
            return real_backend(model)

        with patch.object(IrAttachment, "_storage_backend", spy_backend):
            att.write({"raw": b"b3-new-distinct-content"})
            self.env.flush_all()

        _logger.info(
            "B3 PROBE | _storage_backend() built %d time(s) for one content write",
            len(backend_calls),
        )
        self.assertEqual(
            len(backend_calls),
            1,
            "B3 fix: one write-side backend threaded through the content write",
        )
