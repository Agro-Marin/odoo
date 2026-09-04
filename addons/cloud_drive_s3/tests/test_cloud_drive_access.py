import datetime
from unittest.mock import MagicMock, patch

from psycopg import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.cloud_drive_s3.tools import s3_drive


@tagged("post_install", "-at_install")
class TestCloudDriveAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Access = cls.env["cloud.drive.access"]
        cls.user_a = cls.env["res.users"].create(
            {"name": "Drive User A", "login": "drive_user_a"}
        )
        cls.user_b = cls.env["res.users"].create(
            {"name": "Drive User B", "login": "drive_user_b"}
        )

    def test_unique_folder_user(self):
        self.Access.create(
            {
                "path": "RH",
                "user_id": self.user_a.id,
                "access_level": "read",
            }
        )
        with self.assertRaises(IntegrityError), mute_logger("odoo.db.cursor"):
            with self.cr.savepoint():
                self.Access.create(
                    {
                        "path": "RH",
                        "user_id": self.user_a.id,
                        "access_level": "admin",
                    }
                )
                self.env.flush_all()

    def test_same_folder_different_user_allowed(self):
        row_a = self.Access.create(
            {"path": "RH", "user_id": self.user_a.id, "access_level": "read"}
        )
        row_b = self.Access.create(
            {"path": "RH", "user_id": self.user_b.id, "access_level": "admin"}
        )
        self.assertTrue(row_a.id and row_b.id)

    def test_multi_segment_path_allowed(self):
        row = self.Access.create(
            {
                "path": "06 Partners/ACME/Facturas",
                "user_id": self.user_a.id,
                "access_level": "read",
            }
        )
        self.assertEqual(row.path, "06 Partners/ACME/Facturas")

    def test_reject_traversal_path(self):
        with self.assertRaises(UserError):
            self.Access.create({"path": "06 Partners/../RH", "user_id": self.user_a.id})

    def test_reject_empty_path(self):
        with self.assertRaises(ValidationError):
            self.Access.create({"path": "   ", "user_id": self.user_a.id})

    def test_path_normalized_on_create(self):
        row = self.Access.create(
            {
                "path": "/06 Partners/ACME/",
                "user_id": self.user_a.id,
                "access_level": "read",
            }
        )
        self.assertEqual(row.path, "06 Partners/ACME")

    def test_path_normalized_on_write(self):
        row = self.Access.create(
            {"path": "RH", "user_id": self.user_a.id, "access_level": "read"}
        )
        row.write({"path": "  Finanzas/2026  "})
        self.assertEqual(row.path, "Finanzas/2026")


@tagged("post_install", "-at_install")
class TestPrunedListing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Access = cls.env["cloud.drive.access"]
        cls.deep = {"06 Partners/ACME/Facturas": 1}
        cls.folder = {"RH": 2}

    def test_ancestors_of_grant_are_traversable(self):
        self.assertTrue(self.Access._can_traverse_in(self.deep, "06 Partners"))
        self.assertTrue(self.Access._can_traverse_in(self.deep, "06 Partners/ACME"))

    def test_grant_folder_itself_traversable(self):
        self.assertTrue(
            self.Access._can_traverse_in(self.deep, "06 Partners/ACME/Facturas")
        )

    def test_siblings_not_traversable(self):
        self.assertFalse(self.Access._can_traverse_in(self.deep, "06 Partners/BIMBO"))
        self.assertFalse(
            self.Access._can_traverse_in(self.deep, "06 Partners/ACME/Contratos")
        )

    def test_unrelated_folder_not_traversable(self):
        self.assertFalse(self.Access._can_traverse_in(self.deep, "RH"))

    def test_passthrough_ancestor_files_hidden(self):
        self.assertFalse(self.Access._can_read_in(self.deep, "06 Partners"))
        self.assertFalse(self.Access._can_read_in(self.deep, "06 Partners/ACME"))

    def test_files_in_grant_subtree_readable(self):
        self.assertTrue(
            self.Access._can_read_in(self.deep, "06 Partners/ACME/Facturas")
        )
        self.assertTrue(
            self.Access._can_read_in(self.deep, "06 Partners/ACME/Facturas/2026")
        )

    def test_folder_grant_covers_subtree(self):
        self.assertTrue(self.Access._can_read_in(self.folder, "RH/Nomina"))
        self.assertEqual(
            self.Access._covering_level_in(self.folder, "RH/Nomina/x.pdf"), 2
        )

    def _mock_pages(self, common_prefixes, contents):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = iter(
            [{"CommonPrefixes": common_prefixes, "Contents": contents}]
        )
        return client

    def test_list_path_prunes_siblings_and_ancestor_files(self):
        client = self._mock_pages(
            [{"Prefix": "06 Partners/ACME/"}, {"Prefix": "06 Partners/BIMBO/"}],
            [
                {
                    "Key": "06 Partners/loose.pdf",
                    "Size": 10,
                    "LastModified": datetime.datetime(2026, 1, 1),
                }
            ],
        )
        with patch.object(s3_drive, "get_drive_client", return_value=(client, "b")):
            result = s3_drive.list_path(
                self.env,
                "06 Partners",
                folder_visible=lambda c: self.Access._can_traverse_in(self.deep, c),
                file_visible=lambda k: self.Access._can_read_in(self.deep, k),
            )
        self.assertEqual([f["path"] for f in result["folders"]], ["06 Partners/ACME"])
        self.assertEqual(result["files"], [])

    def test_list_path_shows_files_within_grant(self):
        client = self._mock_pages(
            [],
            [
                {
                    "Key": "RH/nomina.pdf",
                    "Size": 20,
                    "LastModified": datetime.datetime(2026, 1, 1),
                }
            ],
        )
        with patch.object(s3_drive, "get_drive_client", return_value=(client, "b")):
            result = s3_drive.list_path(
                self.env,
                "RH",
                folder_visible=lambda c: self.Access._can_traverse_in(self.folder, c),
                file_visible=lambda k: self.Access._can_read_in(self.folder, k),
            )
        self.assertEqual([f["name"] for f in result["files"]], ["nomina.pdf"])

    def test_single_shared_file_shows_in_passthrough_folder(self):
        file_grant = {"06 Partners/ACME/report.pdf": 1}
        self.assertTrue(self.Access._can_traverse_in(file_grant, "06 Partners/ACME"))
        self.assertTrue(
            self.Access._can_read_in(file_grant, "06 Partners/ACME/report.pdf")
        )
        self.assertFalse(
            self.Access._can_read_in(file_grant, "06 Partners/ACME/other.pdf")
        )
        client = self._mock_pages(
            [],
            [
                {
                    "Key": "06 Partners/ACME/report.pdf",
                    "Size": 5,
                    "LastModified": datetime.datetime(2026, 1, 1),
                },
                {
                    "Key": "06 Partners/ACME/other.pdf",
                    "Size": 6,
                    "LastModified": datetime.datetime(2026, 1, 1),
                },
            ],
        )
        with patch.object(s3_drive, "get_drive_client", return_value=(client, "b")):
            result = s3_drive.list_path(
                self.env,
                "06 Partners/ACME",
                folder_visible=lambda c: self.Access._can_traverse_in(file_grant, c),
                file_visible=lambda k: self.Access._can_read_in(file_grant, k),
            )
        self.assertEqual([f["name"] for f in result["files"]], ["report.pdf"])
