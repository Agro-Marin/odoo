from collections.abc import Callable
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from odoo import release
from odoo.api import SUPERUSER_ID, Environment
from odoo.libs.constants import (
    ANY_UNIQUE,
)
from odoo.tools import SQL

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .common import _logger


class AssetAttachmentStore:
    TRACKED_BUNDLES = {"web.assets_web"}
    """Bundles whose rebuild broadcasts ``bundle_changed`` on the bus.

    Extend with :meth:`register_tracked_bundle` rather than by editing this
    set: an addon that ships its own top-level bundle needs the same reload
    prompt, and patching a constant in ``base`` was the only way to get it.
    ``web.assets_web`` is the default because it is the bundle pages actually
    load; ``base`` names it as data, and reaches the bus only through the
    ``"bus.bus" in self.env`` guard in :meth:`save_attachment`.
    """

    _CSS_EXTENSIONS = frozenset({"css", "min.css", "css.map"})

    @classmethod
    def register_tracked_bundle(cls, name: str) -> None:
        cls.TRACKED_BUNDLES.add(name)

    _ATTACHMENT_MIMETYPES = MappingProxyType(
        {
            "js": "application/javascript",
            "min.js": "application/javascript",
            "js.map": "application/json",
            "css": "text/css",
            "min.css": "text/css",
            "css.map": "application/json",
        }
    )

    def __init__(
        self,
        env: Environment,
        name: str,
        *,
        assets_params: dict[str, Any],
        rtl: bool,
        autoprefix: bool,
        version_provider: Callable[[str], str],
    ) -> None:
        self.env = env
        self.name = name
        self.assets_params = assets_params
        self.rtl = rtl
        self.autoprefix = autoprefix
        self._version = version_provider

    @staticmethod
    def _like_escape(literal: str) -> str:
        return literal.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def is_css(self, extension: str) -> bool:
        return extension in self._CSS_EXTENSIONS

    def get_asset_url(self, unique: str, extension: str) -> str:
        return self._asset_url(unique, extension, ignore_params=False)

    def get_asset_url_pattern(
        self,
        unique: str = ANY_UNIQUE,
        extension: str = "%",
        ignore_params: bool = False,
    ) -> str:
        return self._asset_url(unique, extension, ignore_params, pattern=True)

    def _asset_url(
        self,
        unique: str,
        extension: str,
        ignore_params: bool,
        pattern: bool = False,
    ) -> str:
        direction = ".rtl" if self.is_css(extension) and self.rtl else ""
        autoprefixed = (
            ".autoprefixed" if self.is_css(extension) and self.autoprefix else ""
        )
        name = self._like_escape(self.name) if pattern else self.name
        bundle_name = f"{name}{direction}{autoprefixed}.{extension}"
        return self.env["ir.asset"]._get_asset_bundle_url(
            bundle_name, unique, self.assets_params, ignore_params
        )

    def _attachment_values(
        self, *, name: str, mimetype: str, raw: bytes, url: str
    ) -> dict[str, Any]:
        return {
            "name": name,
            "mimetype": mimetype,
            "res_model": "ir.ui.view",
            "res_id": False,
            "type": "binary",
            "public": True,
            "raw": raw,
            "url": url,
        }

    def _unlink_attachments(self, attachments: IrAttachment) -> None:
        fname_by_id = {
            attach.id: attach.store_fname
            for attach in attachments
            if attach.store_fname
        }
        table = SQL.identifier(attachments._table)
        self.env.cr.execute(
            SQL(
                """DELETE FROM %s WHERE id IN (
            SELECT id FROM %s WHERE id = ANY(%s) FOR NO KEY UPDATE SKIP LOCKED
        ) RETURNING id""",
                table,
                table,
                list(attachments.ids),
            )
        )
        deleted_ids = {row[0] for row in self.env.cr.fetchall()}
        to_delete = {
            fname
            for attach_id, fname in fname_by_id.items()
            if attach_id in deleted_ids
        }
        if to_delete:
            attachments._storage_delete_multi(to_delete)

    def _clean_attachments(self, extension: str, keep_url: str) -> None:
        ira = self.env["ir.attachment"]
        to_clean_pattern = self.get_asset_url_pattern(extension=extension)
        domain = [
            ("url", "=like", to_clean_pattern),
            ("url", "!=", keep_url),
            ("public", "=", True),
            ("res_model", "=", "ir.ui.view"),
            ("res_id", "=", 0),
            ("create_uid", "=", SUPERUSER_ID),
        ]

        attachments = ira.sudo().search(domain)
        if attachments:
            _logger.info(
                "Deleting attachments %s (matching %s) because it was replaced with %s",
                attachments.ids,
                to_clean_pattern,
                keep_url,
            )
            self._unlink_attachments(attachments)

    def get_attachments(
        self, extension: str, ignore_version: bool = False
    ) -> IrAttachment:
        unique = (
            ANY_UNIQUE
            if ignore_version
            else self._version("css" if self.is_css(extension) else "js")
        )
        url_pattern = self.get_asset_url_pattern(unique=unique, extension=extension)
        query = """
             SELECT max(id)
               FROM ir_attachment
              WHERE create_uid = %s
                AND url like %s
                AND res_model = 'ir.ui.view'
                AND res_id = 0
                AND public = true
           GROUP BY name
           ORDER BY name
        """
        self.env.cr.execute(SQL(query, SUPERUSER_ID, url_pattern))

        attachment_ids = [r[0] for r in self.env.cr.fetchall()]
        if not attachment_ids and not ignore_version:
            fallback_url_pattern = self.get_asset_url_pattern(
                unique=unique,
                extension=extension,
                ignore_params=True,
            )
            similar_attachment_ids = []
            if fallback_url_pattern != url_pattern:
                self.env.cr.execute(SQL(query, SUPERUSER_ID, fallback_url_pattern))
                similar_attachment_ids = [r[0] for r in self.env.cr.fetchall()]
            if similar_attachment_ids:
                similar = (
                    self.env["ir.attachment"].sudo().browse(similar_attachment_ids[0])
                )
                _logger.info(
                    "Found a similar attachment for %s, copying from %s",
                    url_pattern,
                    similar.url,
                )
                url = self.get_asset_url(unique=unique, extension=extension)
                values = self._attachment_values(
                    name=similar.name,
                    mimetype=similar.mimetype,
                    raw=similar.raw,
                    url=url,
                )
                attachment = (
                    self.env["ir.attachment"].with_user(SUPERUSER_ID).create(values)
                )
                attachment_ids = attachment.ids
                self._clean_attachments(extension, url)

        return self.env["ir.attachment"].sudo().browse(attachment_ids)

    def save_attachment(self, extension: str, content: str) -> IrAttachment:
        mimetype = self._ATTACHMENT_MIMETYPES.get(extension)
        if mimetype is None:
            raise ValueError(f"Invalid asset extension {extension!r}")
        ira = self.env["ir.attachment"]

        fname = f"{self.name}.{extension}"
        unique = self._version("css" if self.is_css(extension) else "js")
        url = self.get_asset_url(
            unique=unique,
            extension=extension,
        )
        values = self._attachment_values(
            name=fname, mimetype=mimetype, raw=content.encode("utf-8"), url=url
        )
        attachment = ira.with_user(SUPERUSER_ID).create(values)

        _logger.info(
            "Generating a new asset bundle attachment %s (id:%s)",
            attachment.url,
            attachment.id,
        )

        self._clean_attachments(extension, url)

        if "bus.bus" in self.env and self.name in self.TRACKED_BUNDLES:
            self._broadcast_bundle_changed(unique)

        return attachment

    _BROADCAST_KEY = "assetsbundle.bundle_changed"

    def _broadcast_bundle_changed(self, unique: str) -> None:
        sent = self.env.cr.precommit.data.setdefault(self._BROADCAST_KEY, set())
        if self.name in sent:
            return
        sent.add(self.name)
        self.env["bus.bus"]._sendone(
            "broadcast",
            "bundle_changed",
            {"server_version": release.version},
        )
        _logger.debug("Asset Changed: bundle: %s -- version: %s", self.name, unique)
