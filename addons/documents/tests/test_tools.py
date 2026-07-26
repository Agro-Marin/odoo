from odoo import Command
from odoo.tests.common import TransactionCase

from odoo.addons.documents.tests.test_documents_common import TEXT
from odoo.addons.documents.tools import UserFolder


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
        """The partial read documents relies on now lives on ir.attachment."""
        attachment_sudo = self.document_txt.attachment_id.sudo()
        self.assertEqual(attachment_sudo.raw, b"TEST")
        self.assertEqual(attachment_sudo._read_prefix(2), b"TE")
        self.assertEqual(attachment_sudo._read_prefix(), b"TEST")
        # `bin_size` makes a stored binary column read back as a size string;
        # the primitive must still return content, not b"4.00 bytes".
        self.assertEqual(
            attachment_sudo.with_context(bin_size=True)._read_prefix(2), b"TE"
        )


class TestUserFolderParsing(TransactionCase):
    """`user_folder_id` is a virtual parent; parsing it belongs in one place."""

    def test_parses_every_accepted_spelling(self):
        for value, expected in (
            ("MY", UserFolder(UserFolder.MY)),
            ("COMPANY", UserFolder(UserFolder.COMPANY)),
            ("SHARED", UserFolder(UserFolder.SHARED)),
            ("RECENT", UserFolder(UserFolder.RECENT)),
            ("TRASH", UserFolder(UserFolder.TRASH)),
            # the web client sends folder ids as strings; RPC callers as ints
            ("42", UserFolder(UserFolder.FOLDER, 42)),
            (42, UserFolder(UserFolder.FOLDER, 42)),
        ):
            with self.subTest(value=value):
                self.assertEqual(UserFolder.parse(value), expected)

    def test_unspecified_values_parse_to_none(self):
        """The three ways "no folder given" reaches the parser.

        `False` used to be routed through `str()` (it is an `int` subclass) and
        rejected as the unknown value "False"; an unset `Char` is exactly that.
        """
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
        # Only MY and COMPANY can receive documents: the others are views over
        # documents filed elsewhere, or a state.
        self.assertTrue(UserFolder.parse("MY").is_writable_root)
        self.assertTrue(UserFolder.parse("COMPANY").is_writable_root)
        for value in ("SHARED", "RECENT", "TRASH"):
            self.assertFalse(UserFolder.parse(value).is_writable_root, value)
