from __future__ import annotations

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
    # Model-class imports must stay typing-only: base/models/__init__
    # imports assetsbundle FIRST, and registering ir.attachment before
    # model 'base' exists aborts registry load (house pattern — see
    # ir_attachment.py's own TYPE_CHECKING block).
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .common import _logger


class AssetAttachmentStore:
    """Persist, look up and version-clean one bundle's ``ir.attachment`` artifacts.

    Split out of :class:`AssetsBundle` so the raw-SQL attachment layer — and its
    concurrency handling (``SKIP LOCKED`` deletes, the parallel-transaction
    dedup, the cross-params fallback copy) — lives behind one boundary and is
    testable without a full bundle. Holds no version state: the bundle's version
    is read through the ``version_provider`` callback, leaving
    :class:`AssetsBundle` the single source of truth for checksums.
    """

    # Bundles whose rebuild broadcasts a ``bundle_changed`` bus message.
    TRACKED_BUNDLES = ("web.assets_web",)

    # Stylesheet artifact extensions accepted by ``is_css``.
    _CSS_EXTENSIONS = frozenset({"css", "min.css", "css.map"})

    # Persistable bundle artifacts and their served mimetype; doubles as
    # the ``save_attachment`` extension whitelist (one source of truth —
    # the guard and the lookup used to encode this twice and drift).
    # No ``xml`` / ``min.xml`` entries: template bundles do not persist
    # through this store — the production ESM-template path saves via
    # ``ir_qweb._save_esm_attachment`` instead, and legacy templates ship
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

        Bundle names routinely contain ``_`` (``web.assets_web``), which is
        a single-char wildcard in SQL ``LIKE``: unescaped, the pattern for
        ``test.audit_b`` also matches a sibling ``test.auditXb`` — letting
        ``_clean_attachments`` delete the sibling's attachment and making
        ``get_attachments(ignore_version=True)`` return several names
        (which breaks the singleton ``raw`` read in ``css()``'s degraded
        path).  PostgreSQL's default escape character is the backslash.
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
        ``extension``; ``ignore_params`` widens the match across
        assets-params variants (website, lang).  The bundle *name* is a
        literal: its LIKE metacharacters are escaped (see
        :meth:`_like_escape`), so the pattern never crosses into a
        sibling bundle's attachments.  Split from :meth:`get_asset_url`
        so URL construction and SQL-pattern construction stop sharing
        one signature.
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

        With ``pattern=True`` the bundle name is LIKE-escaped; ``unique``
        and ``extension`` are left untouched — their wildcards
        (``ANY_UNIQUE``, the ``"%"`` extension default) are intentional,
        and their concrete values (7-hex unique, the
        ``_ATTACHMENT_MIMETYPES`` extensions) contain no metacharacters.
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

        The single write-side source for both :meth:`save_attachment` and the
        cross-params fallback copy in :meth:`get_attachments`. The identity
        columns set here — ``res_model='ir.ui.view'``, ``res_id`` (the
        ``Many2oneReference`` integer coerces the ``False`` to ``0``),
        ``public=True``, and ``create_uid=SUPERUSER_ID`` via the creating user
        — are exactly the columns :meth:`get_attachments` / :meth:`_clean_attachments`
        filter on, so the read and write halves cannot drift. ``name`` /
        ``mimetype`` / ``raw`` / ``url`` are the per-artifact payload.
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
        """Unlinks attachments without actually calling unlink, so that the ORM cache is not cleared.

        Specifically, if an attachment is generated while a view is rendered, clearing the ORM cache
        could unload fields loaded with a sudo(), and expected to be readable by the view.
        Such a view would be website.layout when main_object is an ir.ui.view.
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
        """Delete outdated ir.attachment records for this bundle before
        saving a fresh one.

        When `extension` is js we need to check that we are deleting a different version (and not *any*
        version) because, as one of the creates in `save_attachment` can trigger a rollback, the
        call to `_clean_attachments` is made at the end of the method to avoid the rollback
        of an ir.attachment unlink (because we cannot rollback a removal on the filestore), thus we
        must exclude the current bundle.
        """
        ira = self.env["ir.attachment"]
        to_clean_pattern = self.get_asset_url_pattern(extension=extension)
        # Mirror the identity columns ``get_attachments`` reads on (create_uid /
        # res_model / res_id, set by ``_attachment_values``): the delete must
        # never reach a row the read would not surface — otherwise a public
        # attachment that merely shares the URL pattern (a different creator or
        # res_model) would be GC'd here despite being invisible to the serving
        # path. With this the read and delete halves cover the exact same set.
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
        """Return the ir.attachment records for a given bundle. Mitigates an issue where
        parallel transactions generate the same bundle: while the file is not
        duplicated on the filestore (as it is stored according to its hash), there are multiple
        ir.attachment records referencing the same version of a bundle. As we don't want to source
        the same bundle several times when rendering, we group our ir.attachment records
        by file name and only return the one with the max id for each group.

        :param extension: file extension (js, min.js, css)
        :param ignore_version: if ignore_version, the url contains a version => web/assets/%/name.extension
                                (the second '%' corresponds to the version),
                               else: the url contains a version equal to that of the bundle version
                                => web/assets/<version>/name.extension.
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
            # The cross-params fallback only finds anything when an
            # ``_get_asset_bundle_url`` override (website) makes the
            # ``ignore_params=True`` pattern wider than the primary one. In base
            # the two patterns are byte-identical, so re-running the query is a
            # guaranteed-empty second round-trip on every cache miss — skip it.
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
        """Record the given bundle in an ir.attachment and delete
        all other ir.attachments referring to this bundle (with the same name and extension).

        :param extension: extension of the bundle to be recorded
        :param content: bundle content to be recorded

        :return: the created ir.attachment record.
        """
        mimetype = self._ATTACHMENT_MIMETYPES.get(extension)
        if mimetype is None:
            raise ValueError(f"Invalid asset extension {extension!r}")
        ira = self.env["ir.attachment"]

        # The LTR/RTL (and autoprefixed) variants are distinguished by the
        # URL, not the name: ``_asset_url`` injects ``.rtl`` / ``.autoprefixed``
        # segments, and both ``get_attachments`` and ``_clean_attachments``
        # match on that direction-scoped URL pattern — so the two variants
        # never collide despite sharing this ``name``. (Upstream encoded the
        # direction in the name; this fork moved it into the URL.)
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
