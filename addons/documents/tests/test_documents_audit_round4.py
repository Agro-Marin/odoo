"""Regressions found in the round-4 audit of the ``documents`` module.

Each test below failed before the accompanying fix and documents *why* the
behaviour matters, not just what it asserts.
"""

import base64
import json
import zipfile
from io import BytesIO
from unittest.mock import patch

from reportlab.pdfgen import canvas

from odoo import Command, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger
from odoo.tools.pdf import PdfFileReader

from odoo.addons.base.models.ir_cron import IrCron
from odoo.addons.mail.tests.common import mail_new_test_user


class TestDocumentsContentAliases(TransactionCase):
    """``raw`` and ``datas`` are two writable aliases for the same bytes.

    ``documents.document.write`` used to branch on the literal ``"datas"``, so
    the two aliases behaved differently on every content-replacement concern.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Round4 User",
                "login": "round4_user",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )

    def _document(self, name, **vals):
        return (
            self.env["documents.document"]
            .with_user(self.user)
            .create({"name": name, "type": "binary", **vals})
        )

    def test_raw_write_keeps_previous_version(self):
        """Replacing content through ``raw`` must version like ``datas`` does.

        Otherwise the old file is overwritten in place and the document's
        history is silently destroyed -- the version is unrecoverable.
        """
        for field, payload in (("datas", base64.b64encode(b"v2")), ("raw", b"v2")):
            with self.subTest(field=field):
                document = self._document(f"versioned via {field}", raw=b"v1")
                original_attachment = document.attachment_id
                document.write({field: payload})
                document.invalidate_recordset()
                self.assertEqual(
                    len(document.previous_attachment_ids),
                    1,
                    f"writing {field!r} must archive the previous content",
                )
                self.assertEqual(bytes(document.attachment_id.raw), b"v2")
                self.assertEqual(document.attachment_id, original_attachment)

    def test_raw_write_creates_the_missing_attachment(self):
        """Uploading through ``raw`` on a pending request must not vanish.

        A document request has no ``attachment_id`` yet. Writing ``raw`` used to
        be routed to the related field of an *empty* ``ir.attachment`` recordset:
        no attachment was created, no error was raised, and the upload was lost.
        """
        for field, payload in (("datas", base64.b64encode(b"zz")), ("raw", b"zz")):
            with self.subTest(field=field):
                document = self._document(f"request via {field}")
                self.assertFalse(document.attachment_id)
                document.write({field: payload})
                document.invalidate_recordset()
                self.assertTrue(
                    document.attachment_id,
                    f"writing {field!r} must materialize the attachment",
                )
                self.assertEqual(bytes(document.attachment_id.raw), b"zz")

    def test_raw_write_logs_the_request_fulfilment(self):
        """Fulfilling a request must be traceable whichever alias is written."""
        for field, payload in (("datas", base64.b64encode(b"up")), ("raw", b"up")):
            with self.subTest(field=field):
                document = self._document(f"logged via {field}")
                before = len(document.message_ids)
                document.write({field: payload})
                document.invalidate_recordset()
                bodies = document.message_ids.mapped("body")
                self.assertGreater(len(document.message_ids), before)
                self.assertTrue(
                    any("Uploaded by" in (body or "") for body in bodies),
                    f"writing {field!r} must post the request-fulfilment message",
                )


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


class TestDocumentsVersioning(TransactionCase):
    """Going back to an earlier version, and not keeping every one forever."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Version User",
                "login": "round4_versions",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )

    def _document_with_versions(self, contents):
        """A document whose content was replaced once per entry after the first."""
        document = (
            self.env["documents.document"]
            .with_user(self.user)
            .create({"name": "versioned.txt", "type": "binary", "raw": contents[0]})
        )
        for content in contents[1:]:
            document.write({"raw": content})
        document.invalidate_recordset()
        return document

    def test_restore_brings_back_a_chosen_version_without_deleting_any(self):
        """Reverting used to mean deleting every version newer than the target.

        The only path that promoted an older attachment was
        `action_delete_from_history`, as a side effect, and it always promoted
        the newest one.
        """
        document = self._document_with_versions([b"v1", b"v2", b"v3"])
        self.assertEqual(bytes(document.attachment_id.raw), b"v3")
        self.assertEqual(len(document.previous_attachment_ids), 2)
        oldest = min(document.previous_attachment_ids, key=lambda a: a.id)
        self.assertEqual(bytes(oldest.raw), b"v1")

        document.with_user(self.user).action_restore_version(oldest.id)
        document.invalidate_recordset()

        self.assertEqual(bytes(document.attachment_id.raw), b"v1")
        self.assertEqual(
            {bytes(a.raw) for a in document.previous_attachment_ids},
            {b"v2", b"v3"},
            "the version it replaced joins the history; nothing is destroyed",
        )

    def test_restore_is_recorded_on_the_document(self):
        document = self._document_with_versions([b"v1", b"v2"])
        previous = document.previous_attachment_ids
        before = len(document.message_ids)

        document.with_user(self.user).action_restore_version(previous.id)
        document.invalidate_recordset()

        self.assertGreater(len(document.message_ids), before)
        self.assertTrue(
            any(
                "Version restored" in (body or "")
                for body in document.message_ids.mapped("body")
            ),
            "a content revert must leave a trace",
        )

    def test_restore_refuses_a_foreign_attachment(self):
        document = self._document_with_versions([b"v1", b"v2"])
        stranger = self.env["ir.attachment"].create(
            {"name": "elsewhere.txt", "raw": b"nope"}
        )
        with self.assertRaises(UserError):
            document.with_user(self.user).action_restore_version(stranger.id)

    def test_restore_requires_edit(self):
        document = self._document_with_versions([b"v1", b"v2"])
        previous = document.previous_attachment_ids
        viewer = self.env["res.users"].create(
            {
                "name": "Version Viewer",
                "login": "round4_version_viewer",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        document.action_update_access_rights(
            partners={viewer.partner_id: ("view", False)}
        )
        self.assertEqual(document.with_user(viewer).user_permission, "view")

        with self.assertRaises(AccessError):
            document.with_user(viewer).action_restore_version(previous.id)

    def test_history_is_unbounded_by_default(self):
        """Enabling the cap destroys data, so an upgrade must not enable it."""
        document = self._document_with_versions([b"v1", b"v2", b"v3", b"v4"])
        self.assertEqual(len(document.previous_attachment_ids), 3)

    def test_history_is_pruned_to_the_configured_maximum(self):
        """Otherwise a daily-edited document grows a filestore blob a day."""
        self.env["ir.config_parameter"].sudo().set_param("documents.max_versions", "2")
        document = self._document_with_versions([b"v1", b"v2", b"v3", b"v4"])

        self.assertEqual(len(document.previous_attachment_ids), 2)
        self.assertEqual(
            {bytes(a.raw) for a in document.previous_attachment_ids},
            {b"v2", b"v3"},
            "the oldest versions are the ones dropped",
        )
        self.assertEqual(bytes(document.attachment_id.raw), b"v4")


class TestDocumentsDownloadBlocked(TransactionCase):
    """"Can look, cannot take a copy" -- the level between Viewer and None."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = cls.env["res.users"].create(
            {
                "name": "Blocked Viewer",
                "login": "round4_blocked_viewer",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        cls.editor = cls.env["res.users"].create(
            {
                "name": "Blocked Editor",
                "login": "round4_blocked_editor",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        cls.document = cls.env["documents.document"].create(
            {
                "name": "confidential.txt",
                "type": "binary",
                "raw": b"secret",
                "is_download_blocked": True,
            }
        )
        cls.document.action_update_access_rights(
            partners={
                cls.viewer.partner_id: ("view", False),
                cls.editor.partner_id: ("edit", False),
            }
        )

    def test_a_viewer_may_not_download_but_an_editor_may(self):
        self.assertEqual(self.document.with_user(self.viewer).user_permission, "view")
        self.assertFalse(
            self.document.with_user(self.viewer)._is_download_allowed(),
            "a viewer must not be able to take a copy",
        )
        # An editor can replace the content outright, so withholding a copy of
        # it from them would express nothing.
        self.assertEqual(self.document.with_user(self.editor).user_permission, "edit")
        self.assertTrue(self.document.with_user(self.editor)._is_download_allowed())

    def test_an_unblocked_document_is_downloadable_by_viewers(self):
        open_document = self.env["documents.document"].create(
            {"name": "public.txt", "type": "binary", "raw": b"open"}
        )
        open_document.action_update_access_rights(
            partners={self.viewer.partner_id: ("view", False)}
        )
        self.assertTrue(open_document.with_user(self.viewer)._is_download_allowed())

    def test_a_shortcut_follows_its_target(self):
        """The flag belongs to the content, not to the pointer at it."""
        shortcut = self.document.with_user(self.editor).action_create_shortcut(
            location_user_folder_id="MY"
        )
        self.assertFalse(
            shortcut.with_user(self.viewer)._is_download_allowed(),
            "a shortcut must not be a way around the target's setting",
        )

    def test_the_setting_propagates_into_a_folder(self):
        """Blocking a folder is a statement about what it holds.

        Left on the folder alone it would only stop the folder's own zip while
        every file inside it stayed one click away.
        """
        folder = self.env["documents.document"].create(
            {"name": "Restricted folder", "type": "folder"}
        )
        child = self.env["documents.document"].create(
            {"name": "inside.txt", "type": "binary", "folder_id": folder.id}
        )

        folder.action_update_access_rights(is_download_blocked=True)
        child.invalidate_recordset()

        self.assertTrue(folder.is_download_blocked)
        self.assertTrue(child.is_download_blocked, "the contents are blocked too")

    def test_rejects_a_non_boolean(self):
        with self.assertRaises(UserError):
            self.document.action_update_access_rights(is_download_blocked="yes")


@tagged("post_install", "-at_install")
class TestDocumentsDownloadBlockedRoutes(HttpCase):
    def test_blocked_content_is_viewable_but_not_downloadable(self):
        """The preview keeps working: that is the whole point of the setting.

        It is a deterrent rather than a control -- the bytes still reach the
        browser to be displayed -- and what it stops is the one-click download,
        which is what the setting is asked for.
        """
        document = self.env["documents.document"].create(
            {
                "name": "watch-only.txt",
                "type": "binary",
                "raw": b"secret",
                "access_via_link": "view",
                "is_download_blocked": True,
            }
        )

        preview = self.url_open(
            f"/documents/content/{document.access_token}?download=false"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"secret")

        download = self.url_open(f"/documents/content/{document.access_token}")
        self.assertEqual(download.status_code, 403)

    def test_blocked_children_are_left_out_of_a_folder_archive(self):
        """Enforced in the archive walk, so nesting is not a way around it."""
        folder = self.env["documents.document"].create(
            {"name": "Mixed", "type": "folder", "access_via_link": "view"}
        )
        subfolder = self.env["documents.document"].create(
            {
                "name": "Deeper",
                "type": "folder",
                "folder_id": folder.id,
                "access_via_link": "view",
            }
        )
        self.env["documents.document"].create(
            [
                {
                    "name": "free.txt",
                    "type": "binary",
                    "folder_id": folder.id,
                    "access_via_link": "view",
                    "raw": b"free",
                },
                {
                    "name": "blocked.txt",
                    "type": "binary",
                    "folder_id": subfolder.id,
                    "access_via_link": "view",
                    "raw": b"blocked",
                    "is_download_blocked": True,
                },
            ]
        )

        response = self.url_open(f"/documents/content/{folder.access_token}")
        response.raise_for_status()

        names = set(zipfile.ZipFile(BytesIO(response.content)).namelist())
        self.assertIn("free.txt", names)
        self.assertNotIn(
            "Deeper/blocked.txt",
            names,
            "a blocked file must not ride along inside a folder download",
        )


class TestDocumentsAccessLog(TransactionCase):
    """The history `documents.access.last_access_date` cannot keep."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env["documents.access.log"]
        cls.document = cls.env["documents.document"].create(
            {"name": "Audited", "type": "binary", "raw": b"payload"}
        )
        cls.partner = cls.env["res.partner"].create({"name": "Auditee"})

    def _entries(self, action=None):
        domain = [("document_id", "=", self.document.id)]
        if action:
            domain.append(("action", "=", action))
        return self.Log.search(domain)

    def test_repeated_history_is_kept_where_last_access_date_overwrites(self):
        """Two visits an hour apart are two rows, not one overwritten field."""
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "0"
        )
        self.Log._log(self.document, self.partner, "view")
        self.Log._log(self.document, self.partner, "download")
        self.Log._log(self.document, self.partner, "download")

        self.assertEqual(len(self._entries()), 3)
        self.assertEqual(len(self._entries("download")), 2)

    def test_repeat_visits_are_coalesced_within_the_window(self):
        """The log sits on read paths; it must not become a write amplifier."""
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "3600"
        )
        for _ in range(5):
            self.Log._log(self.document, self.partner, "view")

        self.assertEqual(
            len(self._entries("view")), 1, "repeats inside the window collapse"
        )

        # A different action is a different fact, and is recorded separately.
        self.Log._log(self.document, self.partner, "download")
        self.assertEqual(len(self._entries("download")), 1)

    def test_window_is_per_document_and_per_partner(self):
        other_document = self.env["documents.document"].create(
            {"name": "Other audited", "type": "binary", "raw": b"x"}
        )
        other_partner = self.env["res.partner"].create({"name": "Someone else"})

        self.Log._log(self.document | other_document, self.partner, "view")
        self.Log._log(self.document, other_partner, "view")

        self.assertEqual(len(self._entries("view")), 2, "one per partner")
        self.assertEqual(
            len(self.Log.search([("document_id", "=", other_document.id)])),
            1,
            "a batch logs every document in it",
        )

    def test_the_log_is_reachable_from_a_document(self):
        """Captured data nobody can look at is not an audit trail.

        The log is browsable in its own right (Configuration > Access Log) for
        querying across documents; this is the other direction.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "0"
        )
        self.Log._log(self.document, self.partner, "download")

        action = self.document.action_view_access_log()

        self.assertEqual(action["res_model"], "documents.access.log")
        self.assertEqual(action["domain"], [("document_id", "=", self.document.id)])
        self.assertEqual(
            self.env["documents.access.log"].search(action["domain"]).action,
            "download",
        )

    def test_a_manager_only_sees_the_log_of_documents_they_can_reach(self):
        """Otherwise the log leaks the existence of documents you cannot see."""
        manager = self.env["res.users"].create(
            {
                "name": "Log Manager",
                "login": "round4_log_manager",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_manager").id)
                ],
            }
        )
        private = self.env["documents.document"].create(
            {
                "name": "Not for the manager",
                "type": "binary",
                "access_internal": "none",
                "access_via_link": "none",
                "owner_id": self.env.ref("base.user_admin").id,
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "0"
        )
        self.Log._log(private, self.partner, "download")

        self.assertEqual(private.with_user(manager).user_permission, "none")
        self.assertFalse(
            self.env["documents.access.log"]
            .with_user(manager)
            .search([("document_id", "=", private.id)]),
            "the log must not expose a document the manager cannot reach",
        )

    def test_retention_drops_old_entries_only(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_retention_days", "30"
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "0"
        )
        self.Log._log(self.document, self.partner, "view")
        recent = self._entries()
        old = self.Log.create(
            {
                "document_id": self.document.id,
                "partner_id": self.partner.id,
                "action": "download",
                "access_date": fields.Datetime.subtract(fields.Datetime.now(), days=90),
            }
        )

        removed, more = self.Log._gc_access_log()

        self.assertEqual(removed, 1)
        self.assertFalse(more)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists(), "entries inside the window are kept")


@tagged("post_install", "-at_install")
class TestDocumentsAccessLogRoutes(HttpCase):
    def test_download_is_recorded_and_preview_is_not(self):
        """Downloads are the audit-relevant event; previews are noise.

        Serving a download writes, so the route drops its read-only cursor for
        exactly that case -- rather than writing on the read-only path, which
        the dispatcher answers by re-running the whole handler.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.access_log_window", "0"
        )
        document = self.env["documents.document"].create(
            {
                "name": "shared.txt",
                "type": "binary",
                "raw": b"secret",
                "access_via_link": "view",
            }
        )
        Log = self.env["documents.access.log"]

        preview = self.url_open(
            f"/documents/content/{document.access_token}?download=false"
        )
        preview.raise_for_status()
        self.assertFalse(
            Log.search([("document_id", "=", document.id)]),
            "an inline preview must not be recorded as a download",
        )

        download = self.url_open(f"/documents/content/{document.access_token}")
        download.raise_for_status()
        self.assertEqual(download.content, b"secret")

        entries = Log.search([("document_id", "=", document.id)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.action, "download")
        self.assertEqual(
            entries.partner_id,
            self.env.ref("base.public_user").partner_id,
            "an anonymous download is still attributable to the link",
        )


class TestDocumentsSearchPanelCounters(TransactionCase):
    """``enable_counters`` must work on the virtual folder field."""

    def test_search_panel_counters_do_not_crash_and_roll_up(self):
        """Counting used to be a hard 500 on this panel.

        ``user_folder_id`` is a non-stored computed Char, so the generic
        ``_search_panel_domain_image`` took its selection-field branch and raised
        ``KeyError: 'selection'``. Counts are now taken on the stored
        ``folder_id`` and rolled up along that same chain.
        """
        Document = self.env["documents.document"]
        parent = Document.create(
            {"name": "Counted parent", "type": "folder", "access_internal": "edit"}
        )
        child = Document.create(
            {
                "name": "Counted child",
                "type": "folder",
                "folder_id": parent.id,
                "access_internal": "edit",
            }
        )
        Document.create(
            [
                {"name": "direct", "type": "binary", "folder_id": parent.id},
                {"name": "nested a", "type": "binary", "folder_id": child.id},
                {"name": "nested b", "type": "binary", "folder_id": child.id},
            ]
        )

        result = Document.search_panel_select_range(
            "user_folder_id", enable_counters=True, search_domain=[]
        )
        counts = {
            value["id"]: value.get("__count")
            for value in result["values"]
            if isinstance(value["id"], int)
        }

        self.assertEqual(counts[child.id], 2, "a folder counts what it holds")
        # Like every other search panel, the count is over the records the view
        # lists, and the Documents views list subfolders alongside files: the
        # parent holds "direct" plus the child folder itself (2), plus the
        # child's own 2 documents rolled up.
        self.assertEqual(
            counts[parent.id],
            4,
            "an ancestor counts its own items plus its descendants'",
        )

    def test_search_panel_counters_survive_a_parent_cycle(self):
        """Only `folder_id <> id` is enforced, so a 2-node cycle is possible."""
        Document = self.env["documents.document"]
        first = Document.create({"name": "Cycle A", "type": "folder"})
        second = Document.create(
            {"name": "Cycle B", "type": "folder", "folder_id": first.id}
        )
        Document.create({"name": "in cycle", "type": "binary", "folder_id": second.id})
        # Bypass the ORM: `_parent_store` would reject the cycle.
        self.env.cr.execute(
            "UPDATE documents_document SET folder_id = %s WHERE id = %s",
            (second.id, first.id),
        )
        first.invalidate_recordset()

        result = Document.search_panel_select_range(
            "user_folder_id", enable_counters=True, search_domain=[]
        )

        self.assertTrue(result["values"], "the panel must still render")


@tagged("post_install", "-at_install")
class TestDocumentsRound4Controllers(HttpCase):
    """Public/authenticated route hardening."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uploader = mail_new_test_user(
            cls.env,
            login="round4_uploader",
            groups="documents.group_documents_user",
            name="Round4 Uploader",
        )
        png = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
            b"DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        cls.shared_image = cls.env["documents.document"].create(
            {
                "name": "round4.png",
                "type": "binary",
                "raw": png,
                "mimetype": "image/png",
                "access_via_link": "view",
            }
        )
        cls.shared_image.write(
            {"thumbnail": base64.b64encode(png), "thumbnail_status": "present"}
        )

    def test_public_thumbnail_rejects_negative_dimensions(self):
        """A public route must answer 400, not 500, to a hostile query string.

        ``image_process`` raises a bare ``ValueError`` on a negative dimension.
        Only the ``int()`` parsing was guarded, so ``?width=-1`` was an
        unauthenticated 500 -- and a free traceback-log flooder.
        """
        token = self.shared_image.access_token
        self.assertEqual(
            self.url_open(f"/documents/thumbnail/{token}").status_code, 200
        )
        sized = self.url_open(f"/documents/thumbnail/{token}?width=64&height=64")
        self.assertEqual(sized.status_code, 200)
        for query in ("width=-1&height=-1", "width=0&height=-5", "width=-5"):
            with self.subTest(query=query):
                self.assertEqual(
                    self.url_open(f"/documents/thumbnail/{token}?{query}").status_code,
                    400,
                )

    @mute_logger("odoo.http")
    def test_pdf_split_rejects_malformed_payloads(self):
        """Valid JSON of the wrong *shape* used to be a 500.

        The route indexed the client payload inline (``new_file["new_pages"]``,
        ``page["old_file_type"]``, ...), so any deviation surfaced as a
        KeyError/TypeError traceback instead of a 400.
        """
        self.authenticate("round4_uploader", "round4_uploader")
        malformed = [
            '[{"name":"x"}]',
            '[{"name":"x","new_pages":5}]',
            '[{"name":"x","new_pages":[{"old_file_index":0}]}]',
            '{"a":1}',
            '[{"name":"x","new_pages":[{"old_file_type":"document",'
            '"old_file_index":"abc","old_page_number":1}]}]',
            '[{"new_pages":[]}]',
            "not-json",
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                res = self.url_open(
                    "/documents/pdf_split",
                    data={
                        "new_files": payload,
                        "vals": "{}",
                        "csrf_token": http.Request.csrf_token(self),
                    },
                )
                self.assertEqual(res.status_code, 400, payload)

    def test_folder_zip_is_streamed_and_complete(self):
        """The archive goes out as it is produced, not assembled in memory.

        A public folder share used to size the worker's memory by the folder's
        contents: the whole zip was built in a `BytesIO` and handed over in one
        piece. It is now generated into the response, so the reply is chunked
        (no `Content-Length` to know up front) and peak memory is one
        compression buffer.
        """
        Document = self.env["documents.document"]
        folder = Document.create(
            {"name": "Streamed", "type": "folder", "access_via_link": "view"}
        )
        subfolder = Document.create(
            {
                "name": "Nested",
                "type": "folder",
                "folder_id": folder.id,
                "access_via_link": "view",
            }
        )
        Document.create(
            [
                {
                    "name": f"payload{index}.bin",
                    "type": "binary",
                    "folder_id": parent.id,
                    "access_via_link": "view",
                    # Comfortably over the read block, so the streaming path
                    # runs more than one iteration per file.
                    "raw": bytes(300_000),
                }
                for index, parent in enumerate((folder, folder, subfolder))
            ]
        )

        response = self.url_open(f"/documents/content/{folder.access_token}")
        response.raise_for_status()

        self.assertEqual(response.headers.get("Transfer-Encoding"), "chunked")
        self.assertNotIn("Content-Length", response.headers)

        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertIsNone(archive.testzip(), "the archive must not be corrupt")
        names = set(archive.namelist())
        self.assertEqual(
            names,
            {"payload0.bin", "payload1.bin", "Nested/", "Nested/payload2.bin"},
            "every descendant, and the folder entry itself, must be present",
        )
        self.assertEqual(
            {info.file_size for info in archive.infolist() if not info.is_dir()},
            {300_000},
            "content must survive the chunked copy intact",
        )

    @mute_logger("odoo.http", "odoo.addons.documents.controllers.documents")
    def test_oversized_zip_is_refused_before_streaming_starts(self):
        """The caps must still be expressible as a status.

        Once the first byte is on the wire the status is settled, so the limits
        are checked while planning the archive -- before the response begins --
        rather than mid-copy, where they could only truncate the download.
        """
        Document = self.env["documents.document"]
        folder = Document.create(
            {"name": "Too big", "type": "folder", "access_via_link": "view"}
        )
        Document.create(
            [
                {
                    "name": f"file{index}.bin",
                    "type": "binary",
                    "folder_id": folder.id,
                    "access_via_link": "view",
                    "raw": bytes(1000),
                }
                for index in range(3)
            ]
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.zip_max_file_count", "1"
        )

        response = self.url_open(f"/documents/content/{folder.access_token}")

        self.assertEqual(response.status_code, 413)
        self.assertNotEqual(
            response.content[:2], b"PK", "no partial archive may be served"
        )

    def _make_pdf_document(self, pages=3):
        stream = BytesIO()
        pdf = canvas.Canvas(stream)
        for page in range(pages):
            pdf.drawString(100, 100, f"page {page}")
            pdf.showPage()
        pdf.save()
        return self.env["documents.document"].create(
            {
                "name": "source.pdf",
                "type": "binary",
                "raw": stream.getvalue(),
                "mimetype": "application/pdf",
                "owner_id": self.uploader.id,
            }
        )

    def test_pdf_split_accepts_numeric_strings(self):
        """JSON indices arriving as strings must not 404.

        The route mapped document ids to file positions through a dict keyed by
        ``int`` id but looked up with the raw payload value, so a string index
        missed the mapping entirely. Normalizing the payload fixes it; this is
        the *only* behavioural change the validation introduces on input that
        was previously accepted-looking.
        """
        source = self._make_pdf_document(pages=2)
        self.authenticate("round4_uploader", "round4_uploader")
        res = self.url_open(
            "/documents/pdf_split",
            data={
                "vals": json.dumps({"owner_id": self.uploader.id}),
                "new_files": json.dumps(
                    [
                        {
                            "name": "stringy",
                            "new_pages": [
                                {
                                    "old_file_type": "document",
                                    "old_file_index": str(source.id),
                                    "old_page_number": "2",
                                }
                            ],
                        }
                    ]
                ),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        res.raise_for_status()
        self.assertEqual(len(self.env["documents.document"].browse(res.json())), 1)

    def test_pdf_split_still_splits(self):
        """Guard the happy path the payload validation now stands in front of.

        No test exercised a *successful* split through the controller (the only
        one asserted a 403), so the route's payload handling could have been
        broken without any suite noticing. This must pass both before and after
        the validation was added -- that is what makes it a regression guard.
        """
        stream = BytesIO()
        pdf = canvas.Canvas(stream)
        for page in range(3):
            pdf.drawString(100, 100, f"page {page}")
            pdf.showPage()
        pdf.save()
        source = self.env["documents.document"].create(
            {
                "name": "source.pdf",
                "type": "binary",
                "raw": stream.getvalue(),
                "mimetype": "application/pdf",
                "owner_id": self.uploader.id,
            }
        )
        self.authenticate("round4_uploader", "round4_uploader")

        res = self.url_open(
            "/documents/pdf_split",
            data={
                "vals": json.dumps({"owner_id": self.uploader.id}),
                "new_files": json.dumps(
                    [
                        {
                            "name": "first two",
                            "new_pages": [
                                {
                                    "old_file_type": "document",
                                    "old_file_index": source.id,
                                    "old_page_number": 1,
                                },
                                {
                                    "old_file_type": "document",
                                    "old_file_index": source.id,
                                    "old_page_number": 2,
                                },
                            ],
                        },
                        {
                            "name": "last one",
                            "new_pages": [
                                {
                                    "old_file_type": "document",
                                    "old_file_index": source.id,
                                    "old_page_number": 3,
                                }
                            ],
                        },
                    ]
                ),
                "archive": "true",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        res.raise_for_status()

        documents = self.env["documents.document"].browse(res.json())
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents.mapped("name"), ["first two.pdf", "last one.pdf"])
        page_counts = [
            len(PdfFileReader(BytesIO(document.raw), strict=False).pages)
            for document in documents
        ]
        self.assertEqual(page_counts, [2, 1], "pages must be routed to the right file")
        self.assertFalse(
            source.active, "archive=true must still send the original to the trash"
        )

    def test_company_root_upload_grants_the_uploader_edit(self):
        """Every file of a Company-drive upload must stay manageable.

        A document created at the Company root has no owner and no parent
        folder, so only ``access_internal`` ("view") applied: the uploader could
        not rename, move or delete their own upload. The compensation existed but
        (a) tested ``owner_id == base.user_root``, which such a document never
        has, and (b) ran on the loop variable, i.e. on the *last* file only.
        """
        self.authenticate("round4_uploader", "round4_uploader")
        res = self.url_open(
            "/documents/upload/",
            data={
                "user_folder_id": "COMPANY",
                "csrf_token": http.Request.csrf_token(self),
            },
            files=[
                ("ufile", ("a.txt", BytesIO(b"a"), "text/plain")),
                ("ufile", ("b.txt", BytesIO(b"b"), "text/plain")),
                ("ufile", ("c.txt", BytesIO(b"c"), "text/plain")),
            ],
        )
        res.raise_for_status()
        documents = self.env["documents.document"].browse(res.json())
        self.assertEqual(len(documents), 3)
        for document in documents:
            with self.subTest(document=document.name):
                self.assertFalse(document.folder_id)
                self.assertFalse(document.owner_id)
                self.assertEqual(
                    document.with_user(self.uploader).user_permission,
                    "edit",
                    "the uploader must be able to manage the file they uploaded",
                )
        # Granted by the create, not repaired by a second pass: no access-change
        # tracking entry, and no "gained access" note on a document the uploader
        # just created.
        self.assertFalse(
            self.env["documents.access.tracking"]
            .search([], order="id desc", limit=1)
            .filtered(lambda tracking: set(tracking.documents) & set(documents.ids)),
            "granting at create time must not queue an access-tracking entry",
        )


class TestDocumentsMisc(TransactionCase):
    def test_copy_folders_only_returns_a_well_formed_recordset(self):
        """``documents_copy_folders_only`` must not return placeholder slots.

        ``copy`` pre-fills its result by input position with empty recordsets;
        the folders-only mode leaves the file slots untouched, and browsing
        their ``.id`` (``False``) produced a recordset whose ``len()`` and
        ``.ids`` disagreed and which raised on the first field read.
        """
        user = self.env["res.users"].create(
            {
                "name": "Copy user",
                "login": "round4_copy",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        Document = self.env["documents.document"].with_user(user)
        folder = Document.create(
            {"name": "Copied folder", "type": "folder", "access_internal": "edit"}
        )
        document = Document.create(
            {
                "name": "Skipped file",
                "type": "binary",
                "folder_id": folder.id,
                "access_internal": "edit",
            }
        )

        copies = (
            (folder | document)
            .with_context(documents_copy_folders_only=True)
            .copy({"user_folder_id": "MY"})
        )

        self.assertEqual(len(copies), len(copies.ids), "no placeholder slots")
        self.assertEqual(len(copies), 1, "only the folder is copied")
        self.assertTrue(all(copies.mapped("name")), "the result must be readable")

    def test_linking_to_a_record_does_not_spawn_a_second_document(self):
        """Re-binding the attachment must not re-enter document auto-creation.

        `documents.mixin` makes `ir.attachment.write` create a document for any
        attachment landing on a bridged model (hr.employee, project.project,
        product.template, account.move, ...). `_inverse_res_record` guards
        against that with `no_document` -- but set it on a value that a recordset
        union then discarded, because union keeps the *left* operand's
        environment and the accumulator it was unioned into carried the default
        context.

        Linking a document to such a record therefore created a *second*
        document for the same attachment: a duplicate where nothing stops it,
        and a `documents_document_attachment_unique` violation -- surfacing as
        HTTP 422 from `/documents/upload/` -- where the constraint does.
        """
        document = self.env["documents.document"].create(
            {"name": "linked.txt", "type": "binary", "raw": b"payload"}
        )
        partner = self.env["res.partner"].create({"name": "Link target"})

        attachment_class = type(self.env["ir.attachment"])
        with patch.object(
            attachment_class, "_create_document", autospec=True
        ) as create_document:
            document.write({"res_model": "res.partner", "res_id": partner.id})

        self.assertFalse(
            create_document.called,
            "re-binding a document's own attachment must not ask for a new "
            "document to be created for it",
        )
        self.assertEqual(document.attachment_id.res_model, "res.partner")
        self.assertEqual(document.attachment_id.res_id, partner.id)
        self.assertEqual(
            self.env["documents.document"].search_count(
                [("attachment_id", "=", document.attachment_id.id)]
            ),
            1,
            "exactly one document may reference the attachment",
        )

    def test_traceback_folder_survives_a_malformed_parameter(self):
        """``documents.support_folder`` is admin-editable free-form text."""
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.support_folder", "not-an-int"
        )
        folder = self.env["documents.document"]._get_traceback_folder_sudo()
        self.assertTrue(folder.exists())
        self.assertEqual(folder.type, "folder")

    def test_attachment_write_authorizes_before_mutating_the_document(self):
        """A refused attachment re-link must leave the target document untouched.

        ``ir.attachment.write`` filled ``documents.document.attachment_id`` (in
        sudo) *before* ``super().write()`` ran the ACL check on the new target,
        i.e. it mutated a record the caller had not been cleared for.
        """
        users = self.env["res.users"]
        group = Command.link(self.env.ref("documents.group_documents_user").id)
        owner = users.create(
            {"name": "R4 owner", "login": "r4_owner", "group_ids": [group]}
        )
        outsider = users.create(
            {"name": "R4 outsider", "login": "r4_outsider", "group_ids": [group]}
        )
        request_document = (
            self.env["documents.document"]
            .with_user(owner)
            .create(
                {
                    "name": "Private request",
                    "type": "binary",
                    "access_internal": "none",
                    "access_via_link": "none",
                }
            )
        )
        self.assertEqual(request_document.with_user(outsider).user_permission, "none")
        attachment = (
            self.env["ir.attachment"]
            .with_user(outsider)
            .create({"name": "outsider.txt", "raw": b"PWNED"})
        )

        # NOT `assertRaises`: it wraps the block in a savepoint, which rolls the
        # premature mutation back and makes the assertion below vacuous. The
        # point here is precisely that the side effect must not survive a
        # *swallowed* AccessError -- the case a caller that suppresses the error
        # (or any code continuing in the same transaction) would hit.
        raised = False
        try:
            attachment.with_user(outsider).write(
                {"res_model": "documents.document", "res_id": request_document.id}
            )
        except AccessError:
            raised = True
        self.assertTrue(raised, "re-linking to an unwritable document must be refused")

        self.env.flush_all()
        request_document.invalidate_recordset()
        self.assertFalse(
            request_document.attachment_id,
            "the refused write must not have attached anything",
        )
