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
    # Model-class imports must stay typing-only: base/models/__init__ imports
    # assetsbundle FIRST, and registering ir.attachment before model 'base'
    # exists aborts registry load (see ir_attachment.py's TYPE_CHECKING block).
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .common import _logger


class AssetAttachmentStore:
    """Persist, look up and version-clean one bundle's ``ir.attachment`` artifacts.

    Split out of :class:`AssetsBundle` so the raw-SQL attachment layer and its
    concurrency handling (``SKIP LOCKED`` deletes, parallel-transaction dedup,
    cross-params fallback copy) is testable without a full bundle. Holds no
    version state: the version is read through the ``version_provider``
    callback, leaving :class:`AssetsBundle` the source of truth for checksums.
    """

    # Bundles whose rebuild broadcasts a ``bundle_changed`` bus message.
    TRACKED_BUNDLES = ("web.assets_web",)

    # Stylesheet artifact extensions accepted by ``is_css``.
    _CSS_EXTENSIONS = frozenset({"css", "min.css", "css.map"})

    # Persistable bundle artifacts and their served mimetype; doubles as the
    # ``save_attachment`` extension whitelist (one source of truth). No
    # ``xml`` / ``min.xml``: template bundles don't persist here — ESM
    # templates save via ``ir_qweb._save_esm_attachment``, legacy ones ship
    # inside the concatenated ``(min.)js`` artifact.
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
        """Bind the store to a bundle's identity and version source.

        :param version_provider: returns the 7-hex version for an asset type
            (``"js"`` / ``"css"``); keeps the store out of checksum logic.
        """
        self.env = env
        self.name = name
        self.assets_params = assets_params
        self.rtl = rtl
        self.autoprefix = autoprefix
        self._version = version_provider

    @staticmethod
    def _like_escape(literal: str) -> str:
        """Escape LIKE metacharacters so *literal* matches only itself.

        Bundle names routinely contain ``_`` (``web.assets_web``), a single-char
        ``LIKE`` wildcard: unescaped, ``test.audit_b`` also matches a sibling
        ``test.auditXb``, so ``_clean_attachments`` would delete the sibling's
        attachment and ``get_attachments(ignore_version=True)`` return several
        names. PostgreSQL's default escape character is the backslash.
        """
        return literal.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def is_css(self, extension: str) -> bool:
        """Whether ``extension`` denotes a stylesheet artifact."""
        return extension in self._CSS_EXTENSIONS

    def get_asset_url(self, unique: str, extension: str) -> str:
        """Build the real attachment URL for one bundle artifact."""
        return self._asset_url(unique, extension, ignore_params=False)

    def get_asset_url_pattern(
        self,
        unique: str = ANY_UNIQUE,
        extension: str = "%",
        ignore_params: bool = False,
    ) -> str:
        """Build a SQL ``=like`` pattern over this bundle's attachment URLs.

        ``%`` wildcards may appear in ``unique`` (``ANY_UNIQUE``) and
        ``extension``; ``ignore_params`` widens the match across assets-params
        variants (website, lang). The bundle *name* is LIKE-escaped (see
        :meth:`_like_escape`) so the pattern never crosses into a sibling
        bundle's attachments.
        """
        return self._asset_url(unique, extension, ignore_params, pattern=True)

    def _asset_url(
        self,
        unique: str,
        extension: str,
        ignore_params: bool,
        pattern: bool = False,
    ) -> str:
        """Shared URL assembly for :meth:`get_asset_url` and the pattern form.

        With ``pattern=True`` the bundle name is LIKE-escaped; ``unique`` and
        ``extension`` are left untouched — their wildcards (``ANY_UNIQUE``, the
        ``"%"`` default) are intentional and their concrete values contain no
        metacharacters.
        """
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
        """Build the ``ir.attachment`` create payload for one bundle artifact.

        The single write-side source for :meth:`save_attachment` and the
        cross-params fallback copy in :meth:`get_attachments`. The identity
        columns set here (``res_model='ir.ui.view'``, ``res_id`` coerced to
        ``0``, ``public=True``, ``create_uid=SUPERUSER_ID``) are exactly the
        columns :meth:`get_attachments` / :meth:`_clean_attachments` filter on,
        so the read and write halves cannot drift.
        """
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
        """Delete attachments via raw SQL to avoid clearing the ORM cache.

        Calling ``unlink`` here would clear the cache, unloading sudo()-loaded
        fields a mid-render view still expects to read (e.g. website.layout
        when main_object is an ir.ui.view).
        """
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
        # ``SKIP LOCKED`` may leave rows in place; only mark the filestore
        # entries of rows that were actually deleted (the GC's reference
        # check would catch a wrong mark, but don't lean on the backstop).
        deleted_ids = {row[0] for row in self.env.cr.fetchall()}
        to_delete = {
            fname
            for attach_id, fname in fname_by_id.items()
            if attach_id in deleted_ids
        }
        for fpath in to_delete:
            # key-axis dispatch: deletes follow the store key's backend
            attachments._storage_delete(fpath)

    def _clean_attachments(self, extension: str, keep_url: str) -> None:
        """Delete outdated ir.attachment records for this bundle, keeping *keep_url*.

        ``_clean_attachments`` runs at the end of ``save_attachment`` because a
        filestore removal cannot be rolled back if a later create fails; hence
        the fresh version (``keep_url``) is excluded from the delete.
        """
        ira = self.env["ir.attachment"]
        to_clean_pattern = self.get_asset_url_pattern(extension=extension)
        # Mirror the identity columns ``get_attachments`` reads on (create_uid /
        # res_model / res_id): the delete must not reach a row the read would
        # not surface, or a public attachment merely sharing the URL pattern
        # would be GC'd despite being invisible to the serving path.
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
        """Return the ir.attachment records for this bundle.

        Parallel transactions can create several ir.attachment rows for the same
        bundle version (the file itself is hash-deduplicated on the filestore);
        group by name and keep the max id per group so a bundle is sourced once.

        :param ignore_version: match any version (``web/assets/%/name.ext``)
            instead of the current bundle version.
        """
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
            # The cross-params fallback only matches when an
            # ``_get_asset_bundle_url`` override (website) widens the
            # ``ignore_params=True`` pattern. In base the two patterns are
            # identical, so skip the guaranteed-empty second query.
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
                # The pattern LIKE-escapes the bundle name (``\_``); the
                # stored URL must be the real, unescaped one.
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
        """Record the bundle in an ir.attachment and delete the outdated ones.

        :return: the created ir.attachment record.
        """
        mimetype = self._ATTACHMENT_MIMETYPES.get(extension)
        if mimetype is None:
            raise ValueError(f"Invalid asset extension {extension!r}")
        ira = self.env["ir.attachment"]

        # LTR/RTL (and autoprefixed) variants are distinguished by the URL, not
        # the name: ``_asset_url`` injects ``.rtl`` / ``.autoprefixed`` segments
        # that ``get_attachments`` / ``_clean_attachments`` match on, so the
        # variants never collide despite sharing this ``name``. (Upstream
        # encoded the direction in the name; this fork moved it to the URL.)
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

        # For end-user assets (common and backend), send a message on the bus
        # to invite the user to refresh their browser
        if "bus.bus" in self.env and self.name in self.TRACKED_BUNDLES:
            self.env["bus.bus"]._sendone(
                "broadcast",
                "bundle_changed",
                {"server_version": release.version},
            )
            _logger.debug("Asset Changed: bundle: %s -- version: %s", self.name, unique)

        return attachment
