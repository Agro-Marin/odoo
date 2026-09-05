import logging
import mimetypes
import posixpath

from odoo.exceptions import UserError

from . import s3

_logger = logging.getLogger(__name__)

ROLE_BY_LEVEL = {"read": "view", "upload": "edit", "admin": "edit"}
BATCH = 200


class DriveImport:
    def __init__(self, env, client, bucket, region, root_name):
        self.env = env
        self.client = client
        self.bucket = bucket
        self.region = region
        self.documents = (
            env["documents.document"]
            .sudo()
            .with_context(mail_create_nolog=True, mail_notrack=True)
        )
        self.attachments = env["ir.attachment"].sudo().with_context(no_document=True)
        self.root = self.documents.create(
            {
                "name": root_name,
                "type": "folder",
                "access_internal": "none",
                "owner_id": False,
            }
        )
        self.folders = {"": self.root}
        self.files = {}

    def run(self, grants=()):
        self._import_objects()
        skipped = self._apply_grants(grants)
        return {
            "root_id": self.root.id,
            "folders": len(self.folders) - 1,
            "files": len(self.files),
            "grants": len(grants) - len(skipped),
            "skipped_grants": skipped,
        }

    def _folder_for(self, path):
        if path in self.folders:
            return self.folders[path]
        parent, name = posixpath.split(path)
        folder = self.documents.create(
            {
                "name": name,
                "type": "folder",
                "folder_id": self._folder_for(parent).id,
                "access_internal": "none",
                "owner_id": False,
            }
        )
        self.folders[path] = folder
        return folder

    def _import_objects(self):
        paginator = self.client.get_paginator("list_objects_v2")
        pending = []
        for page in paginator.paginate(Bucket=self.bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    self._folder_for(key.rstrip("/"))
                    continue
                parent, name = posixpath.split(key)
                pending.append((key, self._folder_for(parent), name, obj["Size"]))
                if len(pending) >= BATCH:
                    self._create_files(pending)
                    pending = []
        if pending:
            self._create_files(pending)

    def _create_files(self, pending):
        attachments = self.attachments.create(
            [
                {
                    "name": name,
                    "type": "cloud_storage",
                    "url": s3.object_url(self.bucket, self.region, key),
                    "mimetype": _mimetype_of(name),
                    "file_size": size,
                    "res_model": "documents.document",
                }
                for key, _folder, name, size in pending
            ]
        )
        documents = self.documents.create(
            [
                {
                    "name": name,
                    "type": "binary",
                    "attachment_id": attachment.id,
                    "folder_id": folder.id,
                    "access_internal": "none",
                    "owner_id": False,
                }
                for (key, folder, name, _size), attachment in zip(
                    pending, attachments, strict=True
                )
            ]
        )
        for (key, _folder, _name, _size), document in zip(
            pending, documents, strict=True
        ):
            self.files[key] = document

    def _apply_grants(self, grants):
        skipped = []
        for grant in grants:
            target = self.folders.get(grant["path"]) or self.files.get(grant["path"])
            user = self.env["res.users"].sudo().browse(grant["user_id"]).exists()
            role = ROLE_BY_LEVEL.get(grant["access_level"])
            if not (target and user and role):
                skipped.append(grant)
                continue
            partner = user.partner_id
            current = target.access_ids.filtered(
                lambda access, partner=partner: access.partner_id == partner
            ).role
            if current != "edit":
                target.action_update_access_rights(partners={partner: (role, None)})
            if grant["access_level"] == "admin" and not target.owner_id:
                target.owner_id = user
        return skipped


def _mimetype_of(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def import_bucket(env, client, bucket, region, root_name="Cloud", grants=()):
    if "documents.document" not in env:
        raise UserError(
            env._("The Documents app must be installed to import a bucket.")
        )
    return DriveImport(env, client, bucket, region, root_name).run(list(grants))
