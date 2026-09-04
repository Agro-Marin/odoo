from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..tools import s3_drive

LEVELS = {"read": 1, "upload": 2, "admin": 3}


class CloudDriveAccess(models.Model):
    _name = "cloud.drive.access"
    _description = "Cloud Drive Access"
    _order = "path, user_id"

    path = fields.Char(
        required=True,
        help="Drive-relative path of a folder or file, any depth "
        "(e.g. '06 Partners/ACME' or '06 Partners/ACME/x.pdf'). A folder grant "
        "covers the whole subtree; a file grant covers just that file.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        ondelete="cascade",
        help="User who receives the access level below on the path.",
    )
    access_level = fields.Selection(
        selection=[
            ("read", "Viewer"),
            ("upload", "Editor"),
            ("admin", "Manager"),
        ],
        required=True,
        default="read",
    )
    active = fields.Boolean(default=True)

    _path_user_uniq = models.Constraint(
        "UNIQUE(path, user_id)",
        "This folder is already shared with this user. Edit the existing row.",
    )

    def _normalize_path(self, path):
        rel = s3_drive._clean_rel(self.env, path or "")
        if not rel:
            raise ValidationError(self.env._("The folder path is required."))
        return rel

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "path" in vals:
                vals["path"] = self._normalize_path(vals.get("path"))
        return super().create(vals_list)

    def write(self, vals):
        if "path" in vals:
            vals["path"] = self._normalize_path(vals.get("path"))
        return super().write(vals)

    @api.depends("path", "user_id", "access_level")
    def _compute_display_name(self):
        labels = dict(self._fields["access_level"].selection)
        for record in self:
            record.display_name = (
                f"{record.path} · {record.user_id.name} "
                f"({labels.get(record.access_level, record.access_level)})"
            )

    def granted_paths(self, user):
        grants = self.sudo().search([("user_id", "=", user.id)])
        out = {}
        for grant in grants:
            level = LEVELS.get(grant.access_level, 0)
            if level > out.get(grant.path, 0):
                out[grant.path] = level
        return out

    def _covering_level_in(self, grants, key):
        key = self._normalize_path(key) if key else ""
        best = 0
        for path, level in grants.items():
            if key == path or key.startswith(path + "/"):
                best = max(best, level)
        return best

    def _can_traverse_in(self, grants, path):
        path = self._normalize_path(path) if path else ""
        if self._covering_level_in(grants, path) >= LEVELS["read"]:
            return True
        prefix = path + "/" if path else ""
        return any(gpath.startswith(prefix) for gpath in grants)

    def _can_read_in(self, grants, key):
        return self._covering_level_in(grants, key) >= LEVELS["read"]

    def _can_write_in(self, grants, key):
        return self._covering_level_in(grants, key) >= LEVELS["upload"]

    def _can_admin_in(self, grants, key):
        return self._covering_level_in(grants, key) >= LEVELS["admin"]

    def can_read(self, user, key):
        return self._covering_level_in(self.granted_paths(user), key) >= LEVELS["read"]

    def can_write(self, user, key):
        return (
            self._covering_level_in(self.granted_paths(user), key) >= LEVELS["upload"]
        )

    def can_admin(self, user, key):
        return self._covering_level_in(self.granted_paths(user), key) >= LEVELS["admin"]

    def can_traverse(self, user, path):
        return self._can_traverse_in(self.granted_paths(user), path)

    def list_grants(self, path):
        norm = self._normalize_path(path)
        grants = self.sudo().search([("path", "=", norm)])
        return [
            {
                "user_id": grant.user_id.id,
                "name": grant.user_id.name,
                "access_level": grant.access_level,
            }
            for grant in grants
        ]

    def set_grant(self, path, user_id, access_level):
        if access_level not in LEVELS:
            raise ValidationError(self.env._("Invalid access level."))
        norm = self._normalize_path(path)
        existing = self.sudo().search(
            [("path", "=", norm), ("user_id", "=", user_id)], limit=1
        )
        if existing:
            existing.access_level = access_level
            return existing
        return self.sudo().create(
            {"path": norm, "user_id": user_id, "access_level": access_level}
        )

    def unset_grant(self, path, user_id):
        norm = self._normalize_path(path)
        self.sudo().search([("path", "=", norm), ("user_id", "=", user_id)]).unlink()
