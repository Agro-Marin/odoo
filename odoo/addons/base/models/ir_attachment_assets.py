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
        # Deleting an asset-bundle attachment must also drop the "assets"
        # ormcache, which stores rendered asset nodes embedding the bundle URL:
        # a cached node that outlives its attachment is a hard 404 on the next
        # request (the ESM serve path, unlike the classic /web/assets
        # controller, has no on-the-fly rebuild). clear_cache() also signals
        # other workers. The hot build-time version rotation goes through
        # _unlink_attachments' raw SQL, which bypasses this on purpose to avoid
        # cross-worker thrash and only ever drops already-superseded versions.
        # Captured before super().unlink() empties the recordset; the cache is
        # cleared after, once the rows are actually gone.
        clear_assets = any(
            url and url.startswith("/web/assets/") for url in self.mapped("url")
        )
        res = super().unlink()
        if clear_assets:
            self.env.registry.clear_cache("assets")
        return res

    @api.model
    def _esm_asset_domain(self) -> Domain:
        """Return the domain identifying server-generated web-asset rows.

        The identity shared by the asset GC and bundle regeneration: a public,
        ir.ui.view-owned (``res_id=0``) attachment created by the superuser
        whose ``url`` lives under ``/web/assets/``.

        :rtype: Domain
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

    @api.autovacuum
    def _gc_esm_assets(self) -> None:
        """Sweep superseded ESM bundle artifacts and aged bridge shims.

        Bundle rebuilds do not delete the previous version inline (the row
        must keep serving in-flight pages, stale CDN HTML and workers that
        have not yet processed the cache-clear signal); this vacuum deletes
        superseded rows once they are older than the grace window, always
        keeping the newest row per artifact name — a stable bundle's only
        row may be years old and must survive.

        Bridge shims (``/web/assets/esm/bridges/<hash>.js``) are
        content-addressed and re-persisted on the next read-write render
        after the cache clear that ``unlink()`` triggers, so age alone is a
        safe criterion for them; a page older than the grace window doing
        its first lazy import of a swept shim 404s until reload — accepted,
        the alternative was unbounded row growth (no other GC path exists).
        """
        get_param = self.env["ir.config_parameter"].sudo().get_param
        try:
            grace_days = int(
                get_param("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS)
            )
        except TypeError, ValueError:
            grace_days = self._ESM_GC_GRACE_DAYS
        # Floor at one day: 0/negative makes cutoff >= now and sweeps every
        # bridge (which has no newest-per-name protection) on every run.
        grace_days = max(1, grace_days)
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)

        # Asset rows as created by _save_esm_attachment / _save_esm_sidecar /
        # _persist_bridge_shims. The name suffixes also catch the legacy
        # ``/web/assets/<ver>/<bundle>.esm.js`` layout while excluding the
        # classic ``.min.js`` bundles, which have their own rotation.
        candidates = self.sudo().search(
            self._esm_asset_domain()
            & Domain("write_date", "<", cutoff)
            & Domain.OR(
                [
                    [("url", "=like", "/web/assets/esm/bridges/%")],
                    [("name", "=like", "%.esm.js")],
                    [("name", "=like", "%.esm.js.map")],
                    [("name", "=like", "%.meta.json")],
                ]
            )
        )
        if not candidates:
            return

        bridges = candidates.filtered(
            lambda a: a.url.startswith("/web/assets/esm/bridges/")
        )
        artifacts = candidates - bridges
        stale_artifacts = self.browse()
        if artifacts:
            # The newest row per name is the live version. It must be
            # computed over ALL rows of that name — not just the over-grace
            # candidates — otherwise a superseded row whose successor is
            # younger than the cutoff would pose as "newest" forever.
            live_ids = {
                max_id
                # Same population as `candidates` (minus the grace/suffix
                # filters): a serving-group user could otherwise create a
                # higher-id same-named row that poses as "newest", marking the
                # real bundle stale.
                for _name, max_id in self.sudo()._read_group(
                    self._esm_asset_domain()
                    & Domain("name", "in", list(set(artifacts.mapped("name")))),
                    ["name"],
                    ["id:max"],
                )
            }
            stale_artifacts = artifacts.filtered(lambda a: a.id not in live_ids)

        to_gc = stale_artifacts | bridges
        if to_gc:
            # unlink() handles the filestore entries and, because the URLs
            # are under /web/assets/, clears the "assets" ormcache so the
            # next render re-persists any bridge shim still in use (same
            # content hash, same URL — browser caches stay valid).
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
        self.search(self._esm_asset_domain()).unlink()
        self.env.registry.clear_cache("assets")
