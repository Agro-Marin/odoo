import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

ASSETS_URL_PREFIX = "/web/assets/"
ESM_BRIDGES_URL_PREFIX = "/web/assets/esm/bridges/"


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    _ESM_GC_GRACE_DAYS = 7

    def unlink(self) -> bool:
        clear_assets = any(
            url and url.startswith(ASSETS_URL_PREFIX) for url in self.mapped("url")
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
                ("url", "=like", f"{ASSETS_URL_PREFIX}%"),
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
                [("url", "=like", f"{ESM_BRIDGES_URL_PREFIX}%")],
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
        grace_days = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS)
        )
        grace_days = max(1, grace_days)
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)

        candidates = self.sudo().search(
            self._esm_generated_asset_domain() & Domain("write_date", "<", cutoff)
        )
        if not candidates:
            return

        bridges = candidates.filtered(
            lambda a: a.url.startswith(ESM_BRIDGES_URL_PREFIX)
        )
        artifacts = candidates - bridges
        stale_artifacts = self.browse()
        if artifacts:
            live_ids = set()
            seen_names = set()
            for att in self.sudo().search_fetch(
                self._generated_asset_domain()
                & Domain("name", "in", list(set(artifacts.mapped("name")))),
                ["name"],
                order="write_date desc, id desc",
            ):
                if att.name not in seen_names:
                    seen_names.add(att.name)
                    live_ids.add(att.id)
            stale_artifacts = artifacts.filtered(lambda a: a.id not in live_ids)

        to_gc = stale_artifacts | bridges
        if to_gc:
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
        self._check_admin_action()
        generated = self.search(self._generated_asset_domain())
        if generated:
            generated.unlink()
        else:
            self.env.registry.clear_cache("assets")
