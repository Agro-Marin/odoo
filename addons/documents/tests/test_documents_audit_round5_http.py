"""Round-5 audit findings reachable only through the HTTP routes."""

import json
import zipfile
from io import BytesIO

from odoo import http
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .test_documents_common import TEXT
from odoo.addons.base.tests.common import HttpCaseWithUserDemo
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestDocumentsZipShortcuts(HttpCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Document = cls.env["documents.document"]
        # A shared folder holding a shortcut to another folder that has content.
        cls.shared_folder = Document.create(
            {
                "name": "Shared",
                "type": "folder",
                "access_via_link": "view",
                "access_internal": "none",
            }
        )
        cls.target_folder = Document.create(
            {
                "name": "Target",
                "type": "folder",
                "access_via_link": "view",
                "access_internal": "none",
            }
        )
        cls.target_child = Document.create(
            {
                "name": "inside_target.txt",
                "type": "binary",
                "datas": TEXT,
                "folder_id": cls.target_folder.id,
                "access_via_link": "view",
            }
        )
        cls.nested_folder = Document.create(
            {
                "name": "Nested",
                "type": "folder",
                "folder_id": cls.target_folder.id,
                "access_via_link": "view",
            }
        )
        cls.nested_child = Document.create(
            {
                "name": "inside_nested.txt",
                "type": "binary",
                "datas": TEXT,
                "folder_id": cls.nested_folder.id,
                "access_via_link": "view",
            }
        )
        cls.shortcut = cls.target_folder.action_create_shortcut(
            location_user_folder_id=str(cls.shared_folder.id)
        )

    def _entries(self, document):
        response = self.url_open(
            f"/documents/content/{document.access_token}", allow_redirects=False
        )
        self.assertEqual(response.status_code, 200)
        return set(zipfile.ZipFile(BytesIO(response.content)).namelist())

    def test_folder_shortcut_carries_the_target_contents(self):
        """A shortcut to a folder must zip what the folder holds.

        `_plan_zip_entries` recursed with `_get_folder_children(<the shortcut>)`,
        and children hang off the target, never off the shortcut -- so the
        archive carried an entry for the folder and nothing inside it. A
        shortcut to a *file* has always been resolved (see
        `test_doc_ctrl_content_folder`); this is the same promise for folders.
        """
        entries = self._entries(self.shared_folder)

        self.assertIn("Target/", entries, "the shortcut itself is listed")
        self.assertIn(
            "Target/inside_target.txt",
            entries,
            "a shortcut to a folder downloaded as an EMPTY directory",
        )
        self.assertIn("Target/Nested/", entries)
        self.assertIn("Target/Nested/inside_nested.txt", entries)

    def test_folder_shortcut_hides_an_unreachable_target(self):
        """Resolving the shortcut must not widen what the link grants."""
        self.target_child.access_via_link = "none"
        self.nested_folder.access_via_link = "none"

        entries = self._entries(self.shared_folder)

        self.assertIn("Target/", entries)
        self.assertNotIn("Target/inside_target.txt", entries)
        self.assertNotIn("Target/Nested/", entries)

    def test_folder_shortcut_cycle_terminates(self):
        """A shortcut pointing back up the tree must not loop forever."""
        self.env["documents.document"].create(
            {
                "name": "loop",
                "type": "folder",
                "folder_id": self.target_folder.id,
                "access_via_link": "view",
            }
        )
        self.shared_folder.action_create_shortcut(
            location_user_folder_id=str(self.target_folder.id)
        )

        entries = self._entries(self.shared_folder)

        self.assertIn("Target/inside_target.txt", entries)


@tagged("post_install", "-at_install")
class TestDocumentsPdfSplitTargets(HttpCaseWithUserDemo):
    """`/documents/pdf_split` fed a well-formed payload naming a bad document.

    Round 4 hardened the payload's *shape*; the documents it names are still
    client-supplied and were dereferenced without a second thought.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.splitter = mail_new_test_user(
            cls.env,
            login="round5_splitter",
            password="round5_splitter",
            groups="base.group_user,documents.group_documents_user",
        )

    def _split(self, document_id):
        return self.url_open(
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
                                    "old_file_index": document_id,
                                    "old_page_number": 1,
                                }
                            ],
                        }
                    ]
                ),
                "csrf_token": http.Request.csrf_token(self),
            },
        )

    @mute_logger("odoo.http")
    def test_split_a_document_with_no_content(self):
        """A pending request document has no bytes to split."""
        self.authenticate("round5_splitter", "round5_splitter")
        document = (
            self.env["documents.document"]
            .with_user(self.splitter)
            .create({"name": "awaiting.pdf", "type": "binary"})
        )
        self.assertFalse(document.attachment_id)
        self.assertEqual(self._split(document.id).status_code, 400)

    @mute_logger("odoo.http")
    def test_split_a_shortcut(self):
        """A shortcut holds no attachment of its own."""
        self.authenticate("round5_splitter", "round5_splitter")
        Document = self.env["documents.document"].with_user(self.splitter)
        target = Document.create({"name": "real.pdf", "type": "binary", "datas": TEXT})
        shortcut = target.action_create_shortcut(location_user_folder_id="MY")
        self.assertFalse(shortcut.attachment_id)
        self.assertEqual(self._split(shortcut.id).status_code, 400)

    @mute_logger("odoo.http")
    def test_split_a_document_that_does_not_exist(self):
        """An id nobody ever created must not be a traceback."""
        self.authenticate("round5_splitter", "round5_splitter")
        missing_id = (
            self.env["documents.document"].search([], order="id desc", limit=1).id
        )
        self.assertIn(self._split(missing_id + 10_000).status_code, (400, 403, 404))
