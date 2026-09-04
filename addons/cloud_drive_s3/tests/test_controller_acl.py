from unittest.mock import patch

from odoo.tests import HttpCase, JsonRpcException, new_test_user, tagged

from odoo.addons.cloud_drive_s3.tools import s3_drive


@tagged("post_install", "-at_install")
class TestCloudDriveAcl(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = "cloud_drive_s3.group_drive_read"
        cls.viewer = new_test_user(
            cls.env, login="drive_viewer", password="drive_viewer", groups=base
        )
        cls.editor = new_test_user(
            cls.env, login="drive_editor", password="drive_editor", groups=base
        )
        cls.manager = new_test_user(
            cls.env, login="drive_manager", password="drive_manager", groups=base
        )
        cls.deep = new_test_user(
            cls.env, login="drive_deep", password="drive_deep", groups=base
        )
        cls.nogrants = new_test_user(
            cls.env, login="drive_nogrants", password="drive_nogrants", groups=base
        )
        cls.filegrantee = new_test_user(
            cls.env, login="drive_file", password="drive_file", groups=base
        )
        cls.admin = new_test_user(
            cls.env,
            login="drive_admin",
            password="drive_admin",
            groups="cloud_drive_s3.group_drive_admin",
        )
        cls.env["cloud.drive.access"].create(
            [
                {"path": "RH", "user_id": cls.viewer.id, "access_level": "read"},
                {
                    "path": "RH",
                    "user_id": cls.editor.id,
                    "access_level": "upload",
                },
                {
                    "path": "RH",
                    "user_id": cls.manager.id,
                    "access_level": "admin",
                },
                {
                    "path": "06 Partners/ACME/Facturas",
                    "user_id": cls.deep.id,
                    "access_level": "read",
                },
                {
                    "path": "06 Partners/ACME/report.pdf",
                    "user_id": cls.filegrantee.id,
                    "access_level": "read",
                },
            ]
        )

    def _assert_denied(self, route, params):
        with self.assertRaises(JsonRpcException) as cm:
            self.call_jsonrpc(route, params)
        self.assertIn("AccessError", str(cm.exception))

    def _assert_allowed(self, route, params, s3_attr, return_value=None):
        rv = return_value if return_value is not None else {"ok": "sentinel"}
        with patch.object(s3_drive, s3_attr, return_value=rv) as mocked:
            self.call_jsonrpc(route, params)
        self.assertTrue(mocked.called, "route was authorized but s3 call not reached")

    def _assert_list_allowed(self, params):
        self._assert_allowed(
            "/cloud_drive_s3/list", params, "list_path", {"folders": [], "files": []}
        )

    def test_viewer_can_list_own_folder(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_list_allowed({"path": "RH"})

    def test_viewer_can_download_in_subtree(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_allowed(
            "/cloud_drive_s3/presign_download",
            {"key": "RH/x.pdf"},
            "presign_download",
        )

    def test_viewer_cannot_move_folder(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_denied("/cloud_drive_s3/move_folder", {"src": "A", "dst": "B"})

    def test_viewer_cannot_copy_folder(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_denied("/cloud_drive_s3/copy_folder", {"src": "A", "dst": "B"})

    def test_viewer_subtree_inheritance(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_list_allowed({"path": "RH/Nomina/2026"})

    def test_viewer_cannot_upload(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_denied("/cloud_drive_s3/presign_upload", {"key": "RH/x.pdf"})

    def test_viewer_cannot_delete(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_denied("/cloud_drive_s3/delete", {"key": "RH/x.pdf"})

    def test_editor_can_upload(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_allowed(
            "/cloud_drive_s3/presign_upload", {"key": "RH/x.pdf"}, "presign_upload"
        )

    def test_editor_can_mkdir(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_allowed(
            "/cloud_drive_s3/mkdir", {"path": "RH", "name": "Sub"}, "make_folder"
        )

    def test_editor_cannot_delete(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied("/cloud_drive_s3/delete", {"key": "RH/x.pdf"})

    def test_editor_copy_denied_when_dst_not_writable(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied(
            "/cloud_drive_s3/copy", {"src": "RH/a.pdf", "dst": "Finanzas/a.pdf"}
        )

    def test_editor_copy_allowed_within_writable(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_allowed(
            "/cloud_drive_s3/copy",
            {"src": "RH/a.pdf", "dst": "RH/b.pdf"},
            "copy_file",
        )

    def test_editor_move_denied_across_folders(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied(
            "/cloud_drive_s3/move", {"src": "RH/a.pdf", "dst": "Finanzas/a.pdf"}
        )

    def test_editor_root_mkdir_denied(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied("/cloud_drive_s3/mkdir", {"path": "", "name": "New"})

    def test_editor_root_upload_denied(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied("/cloud_drive_s3/presign_upload", {"key": "root.pdf"})

    def test_manager_can_delete(self):
        self.authenticate("drive_manager", "drive_manager")
        self._assert_allowed(
            "/cloud_drive_s3/delete", {"key": "RH/x.pdf"}, "delete_file"
        )

    def test_deep_passthrough_can_traverse_ancestors(self):
        self.authenticate("drive_deep", "drive_deep")
        self._assert_list_allowed({"path": "06 Partners"})
        self._assert_list_allowed({"path": "06 Partners/ACME"})

    def test_deep_cannot_download_ancestor_file(self):
        self.authenticate("drive_deep", "drive_deep")
        self._assert_denied(
            "/cloud_drive_s3/presign_download", {"key": "06 Partners/x.pdf"}
        )

    def test_deep_can_download_within_grant(self):
        self.authenticate("drive_deep", "drive_deep")
        self._assert_allowed(
            "/cloud_drive_s3/presign_download",
            {"key": "06 Partners/ACME/Facturas/f.pdf"},
            "presign_download",
        )

    def test_deep_cannot_traverse_sibling(self):
        self.authenticate("drive_deep", "drive_deep")
        self._assert_denied("/cloud_drive_s3/list", {"path": "06 Partners/BIMBO"})

    def test_nogrants_list_denied(self):
        self.authenticate("drive_nogrants", "drive_nogrants")
        self._assert_denied("/cloud_drive_s3/list", {"path": "RH"})

    def test_nogrants_download_denied(self):
        self.authenticate("drive_nogrants", "drive_nogrants")
        self._assert_denied("/cloud_drive_s3/presign_download", {"key": "RH/x.pdf"})

    def test_admin_bypass_delete_anywhere(self):
        self.authenticate("drive_admin", "drive_admin")
        self._assert_allowed(
            "/cloud_drive_s3/delete", {"key": "any/where/x.pdf"}, "delete_file"
        )

    def test_admin_bypass_list_root(self):
        self.authenticate("drive_admin", "drive_admin")
        self._assert_list_allowed({"path": ""})

    def test_admin_bypass_root_mkdir(self):
        self.authenticate("drive_admin", "drive_admin")
        self._assert_allowed(
            "/cloud_drive_s3/mkdir", {"path": "", "name": "NewTop"}, "make_folder"
        )

    def test_manager_can_list_share(self):
        self.authenticate("drive_manager", "drive_manager")
        result = self.call_jsonrpc("/cloud_drive_s3/share/list", {"path": "RH"})
        user_ids = [g["user_id"] for g in result["grants"]]
        self.assertIn(self.viewer.id, user_ids)

    def test_viewer_cannot_list_share(self):
        self.authenticate("drive_viewer", "drive_viewer")
        self._assert_denied("/cloud_drive_s3/share/list", {"path": "RH"})

    def test_editor_cannot_set_share(self):
        self.authenticate("drive_editor", "drive_editor")
        self._assert_denied(
            "/cloud_drive_s3/share/set",
            {"path": "RH", "user_id": self.nogrants.id, "access_level": "read"},
        )

    def test_manager_can_set_and_unset_share(self):
        self.authenticate("drive_manager", "drive_manager")
        self.call_jsonrpc(
            "/cloud_drive_s3/share/set",
            {"path": "RH", "user_id": self.nogrants.id, "access_level": "read"},
        )
        grants = self.call_jsonrpc("/cloud_drive_s3/share/list", {"path": "RH"})[
            "grants"
        ]
        self.assertIn(self.nogrants.id, [g["user_id"] for g in grants])
        self.call_jsonrpc(
            "/cloud_drive_s3/share/unset",
            {"path": "RH", "user_id": self.nogrants.id},
        )
        grants = self.call_jsonrpc("/cloud_drive_s3/share/list", {"path": "RH"})[
            "grants"
        ]
        self.assertNotIn(self.nogrants.id, [g["user_id"] for g in grants])

    def test_set_share_upserts(self):
        self.authenticate("drive_manager", "drive_manager")
        self.call_jsonrpc(
            "/cloud_drive_s3/share/set",
            {"path": "RH", "user_id": self.viewer.id, "access_level": "upload"},
        )
        grants = self.call_jsonrpc("/cloud_drive_s3/share/list", {"path": "RH"})[
            "grants"
        ]
        viewer_rows = [g for g in grants if g["user_id"] == self.viewer.id]
        self.assertEqual(len(viewer_rows), 1)
        self.assertEqual(viewer_rows[0]["access_level"], "upload")

    def test_share_root_denied_even_for_admin(self):
        self.authenticate("drive_admin", "drive_admin")
        self._assert_denied(
            "/cloud_drive_s3/share/set",
            {"path": "", "user_id": self.nogrants.id, "access_level": "read"},
        )

    def test_admin_can_share_any_folder(self):
        self.authenticate("drive_admin", "drive_admin")
        result = self.call_jsonrpc("/cloud_drive_s3/share/list", {"path": "Finanzas"})
        self.assertEqual(result["grants"], [])

    def test_share_user_search(self):
        self.authenticate("drive_viewer", "drive_viewer")
        result = self.call_jsonrpc(
            "/cloud_drive_s3/share/users", {"query": "drive_manager"}
        )
        self.assertIn(self.manager.id, [u["id"] for u in result["users"]])

    def test_filegrantee_can_traverse_ancestors(self):
        self.authenticate("drive_file", "drive_file")
        self._assert_list_allowed({"path": "06 Partners"})
        self._assert_list_allowed({"path": "06 Partners/ACME"})

    def test_filegrantee_can_download_shared_file(self):
        self.authenticate("drive_file", "drive_file")
        self._assert_allowed(
            "/cloud_drive_s3/presign_download",
            {"key": "06 Partners/ACME/report.pdf"},
            "presign_download",
        )

    def test_filegrantee_cannot_download_sibling(self):
        self.authenticate("drive_file", "drive_file")
        self._assert_denied(
            "/cloud_drive_s3/presign_download", {"key": "06 Partners/ACME/other.pdf"}
        )
