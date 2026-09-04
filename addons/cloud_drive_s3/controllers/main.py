from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..tools import s3_drive

ADMIN_GROUP = "cloud_drive_s3.group_drive_admin"
READ_GROUP = "cloud_drive_s3.group_drive_read"


class CloudDriveController(http.Controller):
    def _acl(self):
        return request.env["cloud.drive.access"].sudo()

    def _is_admin(self):
        return request.env.user.has_group(ADMIN_GROUP)

    def _authorize(self, key, need):
        user = request.env.user
        if self._is_admin():
            return
        if not user.has_group(READ_GROUP):
            raise AccessError(
                request.env._("You are not allowed to perform this Cloud action.")
            )
        acl = self._acl()
        checks = {
            "traverse": acl.can_traverse,
            "read": acl.can_read,
            "write": acl.can_write,
            "admin": acl.can_admin,
        }
        if not checks[need](user, key):
            raise AccessError(
                request.env._("You are not allowed to perform this Cloud action.")
            )

    @http.route("/cloud_drive_s3/list", type="jsonrpc", auth="user")
    def list_dir(self, path=""):
        self._authorize(path, "traverse")
        if self._is_admin():
            result = s3_drive.list_path(request.env, path)
            for entry in result["folders"] + result["files"]:
                entry["can_share"] = True
            result["can_write_here"] = True
            return result
        acl = self._acl()
        grants = acl.granted_paths(request.env.user)
        result = s3_drive.list_path(
            request.env,
            path,
            folder_visible=lambda child: acl._can_traverse_in(grants, child),
            file_visible=lambda key: acl._can_read_in(grants, key),
        )
        for entry in result["folders"]:
            entry["can_share"] = acl._can_admin_in(grants, entry["path"])
        for entry in result["files"]:
            entry["can_share"] = acl._can_admin_in(grants, entry["key"])
        result["can_write_here"] = acl._can_write_in(grants, path)
        return result

    @http.route("/cloud_drive_s3/presign_download", type="jsonrpc", auth="user")
    def presign_download(self, key):
        self._authorize(key, "read")
        return {"url": s3_drive.presign_download(request.env, key)}

    @http.route("/cloud_drive_s3/presign_upload", type="jsonrpc", auth="user")
    def presign_upload(self, key, content_type=None, size=0):
        self._authorize(key, "write")
        if size and size > s3_drive.MAX_UPLOAD_BYTES:
            return {"error": "too_large", "limit": s3_drive.MAX_UPLOAD_BYTES}
        return s3_drive.presign_upload(request.env, key, content_type)

    @http.route("/cloud_drive_s3/mkdir", type="jsonrpc", auth="user")
    def mkdir(self, path="", name=""):
        self._authorize(path, "write")
        s3_drive.make_folder(request.env, path, name)
        return {"ok": True}

    @http.route("/cloud_drive_s3/delete", type="jsonrpc", auth="user")
    def delete(self, key=None, folder=None):
        self._authorize(folder or key, "admin")
        if folder:
            s3_drive.delete_folder(request.env, folder)
        else:
            s3_drive.delete_file(request.env, key)
        return {"ok": True}

    @http.route("/cloud_drive_s3/copy", type="jsonrpc", auth="user")
    def copy(self, src, dst):
        self._authorize(src, "read")
        self._authorize(dst, "write")
        s3_drive.copy_file(request.env, src, dst)
        return {"ok": True}

    @http.route("/cloud_drive_s3/move", type="jsonrpc", auth="user")
    def move(self, src, dst):
        self._authorize(src, "write")
        self._authorize(dst, "write")
        s3_drive.move_file(request.env, src, dst)
        return {"ok": True}

    @http.route("/cloud_drive_s3/copy_folder", type="jsonrpc", auth="user")
    def copy_folder(self, src, dst):
        self._authorize(src, "read")
        self._authorize(dst, "write")
        s3_drive.copy_folder(request.env, src, dst)
        return {"ok": True}

    @http.route("/cloud_drive_s3/move_folder", type="jsonrpc", auth="user")
    def move_folder(self, src, dst):
        self._authorize(src, "write")
        self._authorize(dst, "write")
        s3_drive.move_folder(request.env, src, dst)
        return {"ok": True}

    @http.route("/cloud_drive_s3/info", type="jsonrpc", auth="user")
    def info(self, key):
        self._authorize(key, "read")
        return s3_drive.object_info(request.env, key)

    def _authorize_share(self, path):
        if not path:
            raise AccessError(request.env._("The bucket root cannot be shared."))
        self._authorize(path, "admin")

    @http.route("/cloud_drive_s3/share/list", type="jsonrpc", auth="user")
    def share_list(self, path):
        self._authorize_share(path)
        return {"grants": self._acl().list_grants(path)}

    @http.route("/cloud_drive_s3/share/set", type="jsonrpc", auth="user")
    def share_set(self, path, user_id, access_level):
        self._authorize_share(path)
        self._acl().set_grant(path, user_id, access_level)
        return {"ok": True}

    @http.route("/cloud_drive_s3/share/unset", type="jsonrpc", auth="user")
    def share_unset(self, path, user_id):
        self._authorize_share(path)
        self._acl().unset_grant(path, user_id)
        return {"ok": True}

    @http.route("/cloud_drive_s3/share/users", type="jsonrpc", auth="user")
    def share_users(self, query="", limit=10):
        if not self._is_admin() and not request.env.user.has_group(READ_GROUP):
            raise AccessError(
                request.env._("You are not allowed to perform this Cloud action.")
            )
        users = (
            request.env["res.users"]
            .sudo()
            .search(
                [("share", "=", False), ("name", "ilike", query)],
                limit=min(limit, 50),
            )
        )
        return {"users": [{"id": user.id, "name": user.name} for user in users]}
