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

    _ESM_GC_BATCH = 1000

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
    def _gc_esm_assets(self) -> tuple[int, int]:
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

        The batch is BOUNDED and reports the autovacuum re-queue pair (IAVAC),
        like ``ir.attachment._gc_rehash_legacy_keys``. It used to search and
        ``unlink`` every aged row in one go: each deletion releases a filestore
        key and clears the ``assets`` cache, so a backlog — the normal state
        after an upgrade rebuilds every bundle in every language — made one
        vacuum method delete tens of thousands of rows in a single transaction,
        with no way to stop it and nothing to report if it ran long. A truthy
        *remaining* re-enqueues this within the run's wall-clock budget, so the
        backlog drains across passes instead of blocking one.
        """
        grace_days = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS)
        )
        grace_days = max(1, grace_days)
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)

        aged = self._esm_generated_asset_domain() & Domain("write_date", "<", cutoff)
        deleted_artifacts = deleted_bridges = 0
        offset = 0
        more = False
        while True:
            if deleted_artifacts + deleted_bridges >= self._ESM_GC_BATCH:
                more = True
                break
            candidates = self.sudo().search(
                aged, order="id", limit=self._ESM_GC_BATCH, offset=offset
            )
            if not candidates:
                break
            stale_artifacts, bridges = self._esm_gc_collectable(candidates)
            to_gc = stale_artifacts | bridges
            # deleted rows leave the result set, so only the kept ones are paged over
            offset += len(candidates) - len(to_gc)
            if not to_gc:
                continue
            to_gc.unlink()
            deleted_artifacts += len(stale_artifacts)
            deleted_bridges += len(bridges)

        if not deleted_artifacts and not deleted_bridges:
            return 0, 0
        _logger.info(
            "GC'd %d stale ESM artifact(s) and %d aged bridge shim(s) "
            "older than %d day(s)",
            deleted_artifacts,
            deleted_bridges,
            grace_days,
        )
        return deleted_artifacts + deleted_bridges, int(more)

    def _esm_gc_collectable(self, candidates):
        """Split *candidates* into ``(stale artifacts, aged bridge shims)``.

        The newest row per artifact name is never stale: a stable bundle's only
        row may be years old, and deleting it would stop serving the bundle
        rather than rotate it. Bridge shims have no such rule — they are
        content-addressed and re-persisted on demand — so age alone collects
        them.
        """
        bridges = candidates.filtered(
            lambda a: a.url.startswith(ESM_BRIDGES_URL_PREFIX)
        )
        artifacts = candidates - bridges
        if not artifacts:
            return self.browse(), bridges
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
        return artifacts.filtered(lambda a: a.id not in live_ids), bridges

    @api.model
    def regenerate_assets_bundles(self) -> None:
        self._check_admin_action()
        generated = self.search(self._generated_asset_domain())
        if generated:
            generated.unlink()
        else:
            self.env.registry.clear_cache("assets")
