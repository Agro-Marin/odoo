"""Autovacuum and crons: the trash, expired shares, the tracking queue.

Named for what it protects, not for the review that produced it.
"""

import base64
import io
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from PIL import Image

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from .test_documents_common import TEXT, TransactionCaseDocuments
from odoo.addons.base.models.ir_cron import IrCron


def _png(color):
    """Return a base64 PNG, i.e. content `image_process` can actually decode."""
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


class TestDocumentsAccessTrackingCron(TransactionCase):
    """The access-tracking queue must always drain."""

    def _run_cron(self):
        """Run the cron entry point without its commits.

        ``ir.cron._commit_progress`` commits, which a test cursor forbids; the
        loop under test is otherwise exercised for real.
        """
        with patch.object(
            IrCron, "_commit_progress", lambda self, *args, **kwargs: float("inf")
        ):
            self.env["documents.access.tracking"]._cron_generate_tracking()

    def test_cron_drops_unrenderable_tracking_instead_of_wedging(self):
        """A partner deleted before the cron ran used to poison the queue.

        ``_create_message_track`` resolves partner ids stored in a JSON payload;
        a deleted one raised ``MissingError``. The row is only unlinked after a
        successful render and the queue is always read oldest-first, so that one
        row blocked *every* later access change from ever being tracked.
        """
        Tracking = self.env["documents.access.tracking"]
        Tracking.search([]).unlink()
        folder = self.env["documents.document"].create(
            {"name": "Tracked folder", "type": "folder"}
        )
        doomed = self.env["res.partner"].create({"name": "Doomed partner"})
        survivor = self.env["res.partner"].create({"name": "Surviving partner"})

        folder.action_update_access_rights(partners={doomed: ("view", False)})
        folder.action_update_access_rights(partners={survivor: ("view", False)})
        self.assertEqual(Tracking.search_count([]), 2)

        doomed.unlink()

        self._run_cron()

        self.assertEqual(
            Tracking.search_count([]),
            0,
            "the queue must drain even when one entry cannot be rendered",
        )

    def test_cron_drains_the_whole_queue_in_one_run(self):
        """One row per cron trigger left the surplus waiting for the monthly run."""
        Tracking = self.env["documents.access.tracking"]
        Tracking.search([]).unlink()
        folder = self.env["documents.document"].create(
            {"name": "Batched folder", "type": "folder"}
        )
        for index in range(3):
            partner = self.env["res.partner"].create({"name": f"Member {index}"})
            folder.action_update_access_rights(partners={partner: ("view", False)})
        self.assertEqual(Tracking.search_count([]), 3)

        self._run_cron()

        self.assertEqual(Tracking.search_count([]), 0)


class TestDocumentsAccessGc(TransactionCase):
    """Expiring a membership must not erase the access log."""

    def test_gc_expired_keeps_the_last_access_date(self):
        """``last_access_date`` backs "Recent"; an expired *share* must not drop it."""
        document = self.env["documents.document"].create(
            {"name": "Visited document", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "Visitor"})
        access = self.env["documents.access"].create(
            {
                "document_id": document.id,
                "partner_id": partner.id,
                "role": "view",
                "last_access_date": fields.Datetime.now(),
                "expiration_date": fields.Datetime.subtract(
                    fields.Datetime.now(), days=1
                ),
            }
        )

        self.env["documents.access"]._gc_expired()

        self.assertTrue(access.exists(), "the access log row must survive")
        self.assertFalse(access.role, "the expired membership must be revoked")
        self.assertFalse(access.expiration_date)
        self.assertTrue(access.last_access_date, "the visit must still be recorded")

    def test_gc_expired_runs_in_the_autovacuum_environment(self):
        """The GC now *writes* instead of unlinking; ``write`` re-checks ACLs.

        The autovacuum cron runs as ``base.user_root``, and ``Environment``
        forces superuser mode for that uid, so the check cannot bite -- but a
        cross-company document is exactly where it would if that ever changed,
        so pin the behaviour rather than assume it.
        """
        other_company = self.env["res.company"].create({"name": "Round4 Other Co"})
        documents = self.env["documents.document"].create(
            [
                {"name": "Local doc", "type": "binary"},
                {
                    "name": "Other-company doc",
                    "type": "binary",
                    "company_id": other_company.id,
                },
            ]
        )
        partner = self.env["res.partner"].create({"name": "Expiring member"})
        accesses = self.env["documents.access"].create(
            [
                {
                    "document_id": document.id,
                    "partner_id": partner.id,
                    "role": "view",
                    "last_access_date": fields.Datetime.now(),
                    "expiration_date": fields.Datetime.subtract(
                        fields.Datetime.now(), days=1
                    ),
                }
                for document in documents
            ]
        )

        # `_run_vacuum_cleaner` commits per method, so it cannot run on a test
        # cursor; reproduce the environment it calls the GC in instead.
        cron_env = self.env["documents.access"].with_user(
            self.env.ref("base.user_root")
        )
        cron_env._gc_expired()

        self.assertTrue(all(accesses.mapped("last_access_date")))
        self.assertFalse(any(accesses.mapped("role")), "memberships must be revoked")
        self.assertFalse(
            any(accesses.mapped("expiration_date")),
            "clearing the date is what stops the GC reselecting these rows forever",
        )

    def test_gc_expired_still_removes_pure_memberships(self):
        """A row with no access history has nothing left to keep."""
        document = self.env["documents.document"].create(
            {"name": "Unvisited document", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "Never visited"})
        access = self.env["documents.access"].create(
            {
                "document_id": document.id,
                "partner_id": partner.id,
                "role": "view",
                "expiration_date": fields.Datetime.subtract(
                    fields.Datetime.now(), days=1
                ),
            }
        )

        self.env["documents.access"]._gc_expired()

        self.assertFalse(access.exists())


@tagged("post_install", "-at_install")
class TestDocumentsAccessTrackingDrain(TransactionCaseDocuments):
    def test_cron_drains_the_whole_queue_without_recounting(self):
        """The loop knows how many rows are left; it need not re-ask per row.

        `_commit_progress` is stubbed because it commits, which a test cursor
        forbids; the stub also records the ``remaining`` the loop reports, which
        is the value that used to cost a `search_count` apiece.
        """
        Tracking = self.env["documents.access.tracking"]
        Tracking.search([]).unlink()
        Tracking.create(
            [
                {
                    "changes": {"access_internal": "none"},
                    "documents": [self.folder_a.id],
                }
                for _ in range(3)
            ]
        )
        self.env.flush_all()

        reported = []

        def fake_commit_progress(self, processed=0, remaining=None, **kwargs):
            reported.append(remaining)
            return 1  # "there is still time"

        self.patch(type(self.env["ir.cron"]), "_commit_progress", fake_commit_progress)
        Tracking._cron_generate_tracking()

        self.assertFalse(Tracking.search([]), "the queue must be drained")
        self.assertEqual(
            reported,
            [2, 1, 0, 0],
            "remaining is decremented, then reported as drained",
        )


@tagged("post_install", "-at_install")
class TestDocumentsVacuumProgress(TransactionCaseDocuments):
    def test_gc_clear_bin_reports_progress(self):
        """A full batch tells the vacuum there is more to do.

        Returning ``None`` capped trash expiry at one batch per daily vacuum.
        """
        Document = self.env["documents.document"]
        self.assertEqual(Document._gc_clear_bin(), (0, False))

        documents = Document.create(
            [{"name": f"trash {i}", "type": "binary"} for i in range(3)]
        )
        documents.action_archive()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE documents_document SET write_date = write_date - interval '1 year'"
            " WHERE id = ANY(%s)",
            [documents.ids],
        )
        self.env.invalidate_all()

        done, more = Document._gc_clear_bin()
        self.assertEqual(done, 3)
        self.assertFalse(more)
        self.assertFalse(documents.exists())

    def test_gc_expired_access_reports_progress(self):
        Access = self.env["documents.access"]
        self.assertEqual(Access._gc_expired(), (0, False))

        document = self.env["documents.document"].create(
            {"name": "shared.txt", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "expiring member"})
        Access.create(
            {
                "document_id": document.id,
                "partner_id": partner.id,
                "role": "view",
                "expiration_date": "2000-01-01 00:00:00",
            }
        )

        done, more = Access._gc_expired()
        self.assertEqual(done, 1)
        self.assertFalse(more)
        self.assertFalse(
            document.access_ids.filtered(lambda a: a.partner_id == partner)
        )

    def test_access_rights_update_survives_a_missing_cron(self):
        """Sharing keeps working when the tracking cron record is gone."""
        document = self.env["documents.document"].create(
            {"name": "shared.txt", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "new member"})
        self.env.ref("documents.ir_cron_documents_access_tracking").sudo().unlink()

        document.action_update_access_rights(
            partners={partner.id: ("view", False)},
        )

        self.assertEqual(
            document.access_ids.filtered(lambda a: a.partner_id == partner).role,
            "view",
        )


@tagged("post_install", "-at_install")
class TestDocumentsTrashExpiry(TransactionCaseDocuments):
    def test_gc_clear_bin_respects_deletion_delay(self):
        """Trashed documents are purged only after the deletion delay."""
        Doc = self.env["documents.document"]
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.deletion_delay", "30"
        )
        doc = Doc.create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "trash.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        doc.action_archive()
        self.assertFalse(doc.active)

        # Freshly trashed: within the delay, it survives the GC.
        Doc._gc_clear_bin()
        self.assertTrue(doc.exists())

        # Back-date past the delay: it is collected.
        self.env.cr.execute(
            "UPDATE documents_document SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - relativedelta(days=31), doc.id),
        )
        doc.invalidate_recordset(["write_date"])
        Doc._gc_clear_bin()
        self.assertFalse(doc.exists())
