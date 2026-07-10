import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    # Grace window (days) before superseded ESM artifacts are vacuumed by
    # _gc_esm_assets; operators override via ``web.esm.gc_grace_days``.
    _ESM_GC_GRACE_DAYS = 7

    def unlink(self) -> bool:
        # Deleting an asset-bundle attachment must drop the "assets" ormcache
        # too: it stores rendered nodes embedding the bundle URL, and a cached
        # node outliving its attachment is a hard 404 (the ESM serve path has
        # no on-the-fly rebuild, unlike the classic /web/assets controller).
        # Build-time version rotation bypasses this via _unlink_attachments' raw
        # SQL to avoid cross-worker thrash. Captured before super() empties the
        # recordset; cache cleared after, once the rows are gone.
        clear_assets = any(
            url and url.startswith("/web/assets/") for url in self.mapped("url")
        )
        res = super().unlink()
        if clear_assets:
            self.env.registry.clear_cache("assets")
        return res

    @api.model
    def _generated_asset_domain(self) -> Domain:
        """Return the domain matching ALL server-generated web-asset rows.

        A public, ir.ui.view-owned (``res_id=0``) attachment created by the
        superuser with a ``url`` under ``/web/assets/``. Matches EVERY
        server-generated asset — classic ``.min.js``/``.min.css`` bundles
        included — not only ESM artifacts; callers needing only ESM rows use
        :meth:`_esm_generated_asset_domain`.
        """
        return Domain(
            [
                ("public", "=", True),
                ("res_model", "=", "ir.ui.view"),
                ("res_id", "=", 0),
                ("create_uid", "=", api.SUPERUSER_ID),
                ("url", "=like", "/web/assets/%"),
            ]
        )

    @api.model
    def _esm_generated_asset_domain(self) -> Domain:
        """Return the domain matching ESM-pipeline artifacts only.

        Narrows :meth:`_generated_asset_domain` to rows created by
        ``IrQweb._save_esm_attachment`` / ``_save_esm_sidecar`` /
        ``BridgeShimManager._persist_bridge_shims``, excluding the classic
        ``.min.js`` bundles (which have their own rotation).
        """
        return self._generated_asset_domain() & Domain.OR(
            [
                [("url", "=like", "/web/assets/esm/bridges/%")],
                [("name", "=like", "%.esm.js")],
                [("name", "=like", "%.esm.js.map")],
                [("name", "=like", "%.meta.json")],
            ]
        )

    @api.autovacuum
    def _gc_esm_assets(self) -> None:
        """Sweep superseded ESM bundle artifacts and aged bridge shims.

        Rebuilds do not delete the previous version inline (it must keep
        serving in-flight pages and not-yet-signalled workers); this vacuum
        deletes superseded rows past the grace window but always keeps the
        newest row per artifact name — a stable bundle's only row may be years
        old and must survive.

        Bridge shims (``/web/assets/esm/bridges/<hash>.js``) are
        content-addressed and re-persisted on the next read-write render after
        ``unlink()``'s cache clear, so age alone is safe for them. A page past
        the grace window lazily importing a swept shim 404s until reload —
        accepted; the alternative is unbounded row growth.
        """
        get_param = self.env["ir.config_parameter"].sudo().get_param
        try:
            grace_days = int(
                get_param("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS)
            )
        except TypeError, ValueError:
            grace_days = self._ESM_GC_GRACE_DAYS
        # Floor at one day: 0/negative makes cutoff >= now and sweeps every
        # bridge (no newest-per-name protection) on every run.
        grace_days = max(1, grace_days)
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)

        candidates = self.sudo().search(
            self._esm_generated_asset_domain() & Domain("write_date", "<", cutoff)
        )
        if not candidates:
            return

        bridges = candidates.filtered(
            lambda a: a.url.startswith("/web/assets/esm/bridges/")
        )
        artifacts = candidates - bridges
        stale_artifacts = self.browse()
        if artifacts:
            # The newest row per name is live. Compute it over ALL rows of
            # that name (not just over-grace candidates), else a superseded row
            # whose successor is younger than the cutoff poses as "newest"
            # forever.
            #
            # "Newest" = freshest ``write_date`` (id tie-break), NOT max id:
            # content-addressed saves REUSE a row when content reverts (rollback
            # A → B → A), and the render path bumps the reused row's
            # ``write_date`` on every uncached reuse
            # (``IrQweb._persist_esm_attachment_rows``). Max-id liveness would
            # keep B (the abandoned newer row) live and sweep A, the row every
            # cached node URL points at (hard 404: no ESM rebuild).
            live_ids = set()
            _seen_names = set()
            # Same population as `candidates` minus the grace/suffix filters,
            # so a same-named row can't pose as "newest" and mark the real
            # bundle stale.
            for att in self.sudo().search(
                self._generated_asset_domain()
                & Domain("name", "in", list(set(artifacts.mapped("name")))),
                order="write_date desc, id desc",
            ):
                if att.name not in _seen_names:
                    _seen_names.add(att.name)
                    live_ids.add(att.id)
            stale_artifacts = artifacts.filtered(lambda a: a.id not in live_ids)

        to_gc = stale_artifacts | bridges
        if to_gc:
            # unlink() drops the filestore entries and, since the URLs are
            # under /web/assets/, clears the "assets" ormcache so the next
            # render re-persists any bridge shim still in use (same content
            # hash and URL — browser caches stay valid).
            to_gc.unlink()
            _logger.info(
                "GC'd %d stale ESM artifact(s) and %d aged bridge shim(s) "
                "older than %d day(s)",
                len(stale_artifacts),
                len(bridges),
                grace_days,
            )

    @api.model
    def regenerate_assets_bundles(self) -> None:
        # Explicit gate (like force_storage): unlink below would already deny
        # non-system users via _check_access, but fail fast and clearly.
        if not self.env.is_admin():
            raise AccessError(_("Only administrators can execute this action."))
        # Deliberately the BROAD domain: regeneration drops every generated
        # bundle artifact (classic .min.js/.min.css included) so the next
        # render rebuilds them all from source.
        self.search(self._generated_asset_domain()).unlink()
        self.env.registry.clear_cache("assets")
