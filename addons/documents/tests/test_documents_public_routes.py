"""Public and portal route hardening.

Named for what it protects, not for the review that produced it.
"""

import base64
import json
import zipfile
from io import BytesIO

from reportlab.pdfgen import canvas

from odoo import Command, http
from odoo.tests.common import HttpCase, tagged
from odoo.tools import mute_logger
from odoo.tools.pdf import PdfFileReader

from .test_documents_common import GIF, TransactionCaseDocuments
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestDocumentsPublicRouteHardening(HttpCase):
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
            (
                '[{"name":"x","new_pages":[{"old_file_type":"document",'
                '"old_file_index":"abc","old_page_number":1}]}]'
            ),
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

    @mute_logger("odoo.http")
    def test_pdf_split_refuses_a_source_that_holds_no_pdf(self):
        """A readable non-PDF source must answer 400, like every other bad input.

        The route resolved each source through ``base64.b64decode(document.datas)``
        and handed the bytes to PyPDF, which raises ``PdfStreamError`` -- not a
        ``ValueError``, so it escaped the route's own mapping and surfaced as an
        HTTP 500 for any document id the caller is merely allowed to read.
        ``ir.attachment._get_pdf_raw`` is the base primitive answering "these
        bytes, if this row holds a PDF", so both refusals are expressed once,
        before anything reaches the parser. The contentless case (a pending
        request, a shortcut) was already a 400 and must stay one.
        """
        not_a_pdf = self.env["documents.document"].create(
            {
                "name": "notes.txt",
                "type": "binary",
                "raw": b"plain text, definitely not a pdf",
                "owner_id": self.uploader.id,
            }
        )
        pending_request = self.env["documents.document"].create(
            {"name": "awaited.pdf", "type": "binary", "owner_id": self.uploader.id}
        )
        self.assertFalse(pending_request.attachment_id)
        self.authenticate("round4_uploader", "round4_uploader")

        for document in (not_a_pdf, pending_request):
            with self.subTest(document=document.name):
                res = self.url_open(
                    "/documents/pdf_split",
                    data={
                        "vals": "{}",
                        "new_files": json.dumps(
                            [
                                {
                                    "name": "out",
                                    "new_pages": [
                                        {
                                            "old_file_type": "document",
                                            "old_file_index": document.id,
                                            "old_page_number": 1,
                                        }
                                    ],
                                }
                            ]
                        ),
                        "csrf_token": http.Request.csrf_token(self),
                    },
                )
                self.assertEqual(res.status_code, 400)

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

    def test_zip_skips_content_the_archive_cannot_carry(self):
        """A remotely-stored file must be left out, not truncate the archive.

        An attachment whose bytes the *client* fetches from a remote store (a
        ``cloud_storage`` row, any binary attachment carrying a url) streams as
        ``type='url'``, and ``Stream.read`` refuses those. The plan pass built
        such an entry happily -- it only resolves streams, it never reads them --
        so the ValueError landed in the streaming pass instead, after the 200
        was already on the wire: an unhandled traceback and an archive that
        stops mid-entry while still looking like a complete download. The plan
        pass is the last point at which that is expressible, so the refusal
        belongs there.
        """
        Document = self.env["documents.document"]
        folder = Document.create(
            {"name": "Mixed", "type": "folder", "access_via_link": "view"}
        )
        Document.create(
            {
                "name": "local.bin",
                "type": "binary",
                "folder_id": folder.id,
                "access_via_link": "view",
                "raw": b"local bytes",
            }
        )
        remote_attachment = self.env["ir.attachment"].create(
            {
                "name": "remote.bin",
                "type": "binary",
                "url": "https://example.invalid/blob/abc",
                "public": True,
            }
        )
        Document.create(
            {
                "name": "remote.bin",
                "type": "binary",
                "folder_id": folder.id,
                "access_via_link": "view",
                "attachment_id": remote_attachment.id,
            }
        )

        response = self.url_open(f"/documents/content/{folder.access_token}")
        response.raise_for_status()

        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertIsNone(archive.testzip(), "the archive must not be corrupt")
        self.assertEqual(archive.namelist(), ["local.bin"])
        self.assertEqual(archive.read("local.bin"), b"local bytes")

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


@tagged("post_install", "-at_install")
class TestPublicFolderBatch(HttpCase, TransactionCaseDocuments):
    """The public folder page fetches every subfolder's children in one search
    (Fix H) and still renders each subfolder's document count correctly."""

    def test_nested_public_folder_renders_subfolder_counts(self):
        root = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "shared root",
                "access_via_link": "view",
                "owner_id": self.doc_user.id,
            }
        )
        sub1, sub2 = self.env["documents.document"].create(
            [
                {
                    "type": "folder",
                    "name": f"sub {n}",
                    "folder_id": root.id,
                    "access_via_link": "view",
                    "owner_id": self.doc_user.id,
                }
                for n in (1, 2)
            ]
        )
        # one file in sub1, two in sub2 (all link-visible)
        self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": "s1-a",
                    "datas": GIF,
                    "folder_id": sub1.id,
                    "access_via_link": "view",
                    "owner_id": self.doc_user.id,
                }
            ]
            + [
                {
                    "type": "binary",
                    "name": f"s2-{i}",
                    "datas": GIF,
                    "folder_id": sub2.id,
                    "access_via_link": "view",
                    "owner_id": self.doc_user.id,
                }
                for i in range(2)
            ]
        )
        res = self.url_open(root.access_url)
        res.raise_for_status()
        body = res.text
        self.assertIn("sub 1", body)
        self.assertIn("sub 2", body)
        # template renders "<count> documents" per subfolder (server-side)
        self.assertIn("1 documents", body)
        self.assertIn("2 documents", body)


@tagged("post_install", "-at_install")
class TestDocumentsPublicRouteInput(HttpCase, TransactionCaseDocuments):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("documents.group_documents_user").id,
        ]
        cls.manager = cls.env["res.users"].create(
            {
                "name": "audit_mgr",
                "login": "audit_mgr",
                "password": "audit_mgr",
                "email": "audit_mgr@t.test",
                "group_ids": [
                    Command.set(
                        groups + [cls.env.ref("documents.group_documents_manager").id]
                    )
                ],
            }
        )
        cls.uploader = cls.env["res.users"].create(
            {
                "name": "audit_up",
                "login": "audit_up",
                "password": "audit_up",
                "email": "audit_up@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        cls.victim = cls.env["res.users"].create(
            {
                "name": "audit_vic",
                "login": "audit_vic",
                "password": "audit_vic",
                "email": "audit_vic@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        cls.viewer = cls.env["res.users"].create(
            {
                "name": "audit_view",
                "login": "audit_view",
                "password": "audit_view",
                "email": "audit_view@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        Doc = cls.env["documents.document"]
        cls.folder = Doc.with_user(cls.manager).create(
            {"type": "folder", "name": "audit_folder", "user_folder_id": "COMPANY"}
        )
        cls.folder.action_update_access_rights(
            access_via_link="edit", partners={cls.uploader.partner_id: ("edit", False)}
        )
        cls.webp = Doc.with_user(cls.manager).create(
            {
                "type": "binary",
                "name": "audit.webp",
                "user_folder_id": "COMPANY",
                "datas": base64.b64encode(b"RIFF....WEBPVP8 "),
                "mimetype": "image/webp",
            }
        )
        cls.webp.action_update_access_rights(
            partners={cls.viewer.partner_id: ("view", False)}
        )

    def test_c3_bad_member_id_is_bad_request(self):
        res = self.url_open(
            f"/documents/{self.folder.access_token}?member_id=NOTANUMBER",
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 400)

    def test_c4_pdf_first_page_rejects_non_pdf(self):
        res = self.url_open(
            f"/documents/content/pdf_first_page/{self.webp.access_token}",
            allow_redirects=False,
        )
        self.assertIn(res.status_code, (400, 404))
