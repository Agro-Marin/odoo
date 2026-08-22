from odoo import Command
from odoo.tests.common import TransactionCase, tagged

from .test_documents_common import TEXT
from odoo.addons.documents.controllers.documents import _is_safe_redirect_url
from odoo.addons.documents.tools import UserFolder, is_mimetype_textual


class TestTools(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document_manager = cls.env["res.users"].create(
            [
                {
                    "email": "dtdm@yourcompany.com",
                    "group_ids": [
                        Command.link(
                            cls.env.ref("documents.group_documents_manager").id
                        )
                    ],
                    "login": "dtdm",
                    "name": "Documents Manager",
                }
            ]
        )
        cls.document_txt = cls.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "file.txt",
                "mimetype": "text/plain",
                "owner_id": cls.document_manager.id,
            }
        )

    def test_read_prefix(self):
        attachment_sudo = self.document_txt.attachment_id.sudo()
        self.assertEqual(attachment_sudo.raw, b"TEST")
        self.assertEqual(attachment_sudo._get_content_prefix(2), b"TE")
        self.assertEqual(attachment_sudo._get_content_prefix(), b"TEST")
        self.assertEqual(
            attachment_sudo.with_context(bin_size=True)._get_content_prefix(2), b"TE"
        )


class TestUserFolderParsing(TransactionCase):

    def test_parses_every_accepted_spelling(self):
        for value, expected in (
            ("MY", UserFolder(UserFolder.MY)),
            ("COMPANY", UserFolder(UserFolder.COMPANY)),
            ("SHARED", UserFolder(UserFolder.SHARED)),
            ("RECENT", UserFolder(UserFolder.RECENT)),
            ("TRASH", UserFolder(UserFolder.TRASH)),
            ("42", UserFolder(UserFolder.FOLDER, 42)),
            (42, UserFolder(UserFolder.FOLDER, 42)),
        ):
            with self.subTest(value=value):
                self.assertEqual(UserFolder.parse(value), expected)

    def test_unspecified_values_parse_to_none(self):
        for value in (None, False, ""):
            with self.subTest(value=value):
                self.assertIsNone(UserFolder.parse(value))

    def test_rejects_unknown_values(self):
        for value in ("ALL", "my", "12x", "-1", 4.2, ["MY"], True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    UserFolder.parse(value)

    def test_round_trips_through_the_wire_format(self):
        for value in ("MY", "COMPANY", "SHARED", "RECENT", "TRASH", "42"):
            with self.subTest(value=value):
                self.assertEqual(str(UserFolder.parse(value)), value)

    def test_distinguishes_folders_from_virtual_roots(self):
        self.assertTrue(UserFolder.parse("42").is_folder)
        self.assertFalse(UserFolder.parse("MY").is_folder)
        self.assertTrue(UserFolder.parse("MY").is_writable_root)
        self.assertTrue(UserFolder.parse("COMPANY").is_writable_root)
        for value in ("SHARED", "RECENT", "TRASH"):
            self.assertFalse(UserFolder.parse(value).is_writable_root, value)


@tagged("post_install", "-at_install")
class TestDocumentsToolHelpers(TransactionCase):

    def test_is_mimetype_textual_handles_bad_input(self):
        self.assertTrue(is_mimetype_textual("text/plain"))
        self.assertTrue(is_mimetype_textual("application/json"))
        self.assertFalse(is_mimetype_textual("image/png"))
        self.assertFalse(is_mimetype_textual(False))
        self.assertFalse(is_mimetype_textual(""))
        self.assertFalse(is_mimetype_textual("notamimetype"))
        self.assertTrue(is_mimetype_textual("text"))

    def test_is_safe_redirect_url(self):
        self.assertTrue(_is_safe_redirect_url("https://example.com"))
        self.assertTrue(_is_safe_redirect_url("http://example.com/x"))
        self.assertTrue(_is_safe_redirect_url("mailto:a@b.c"))
        self.assertTrue(_is_safe_redirect_url("example.com/path"))
        self.assertTrue(_is_safe_redirect_url("//host/path"))
        self.assertFalse(_is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(_is_safe_redirect_url("data:text/html,<script>"))
        self.assertFalse(_is_safe_redirect_url("vbscript:msgbox"))
        self.assertFalse(_is_safe_redirect_url(""))
