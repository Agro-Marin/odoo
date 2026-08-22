import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools.assets.constants import ESM_BRIDGE_REFRESH_DAYS

_logger = logging.getLogger(__name__)

ASSETS_URL_PREFIX = "/web/assets/"
ESM_BRIDGES_URL_PREFIX = "/web/assets/esm/bridges/"


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    _ESM_GC_GRACE_DAYS = 7

    _ESM_BRIDGE_GC_GRACE_DAYS = 90

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
        return self._generated_asset_domain() & Domain.OR(
            [
                [("url", "=like", f"{ESM_BRIDGES_URL_PREFIX}%")],
                [("name", "=like", "%.esm.js")],
                [("name", "=like", "%.esm.js.map")],
                [("name", "=like", "%.meta.json")],
            ]
        )

    @api.model
    def _esm_bridge_gc_grace_days(self) -> int:
        configured = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int(
                "web.esm.bridge_gc_grace_days", self._ESM_BRIDGE_GC_GRACE_DAYS
            )
        )
        return max(int(2 * ESM_BRIDGE_REFRESH_DAYS) + 1, configured)

    @api.model
    def _esm_gc_grace_days(self) -> int:
        return max(
            1,
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("web.esm.gc_grace_days", self._ESM_GC_GRACE_DAYS),
        )

    @api.autovacuum
    def _gc_esm_assets(self) -> tuple[int, int]:
        grace_days = self._esm_gc_grace_days()
        cutoff = fields.Datetime.now() - timedelta(days=grace_days)
        bridge_cutoff = fields.Datetime.now() - timedelta(
            days=self._esm_bridge_gc_grace_days()
        )
        is_bridge = Domain("url", "=like", f"{ESM_BRIDGES_URL_PREFIX}%")
        aged = self._esm_generated_asset_domain() & Domain.OR(
            [
                ~is_bridge & Domain("write_date", "<", cutoff),
                is_bridge & Domain("write_date", "<", bridge_cutoff),
            ]
        )
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
        self._check_admin_access()
        generated = self.search(self._generated_asset_domain())
        if generated:
            generated.unlink()
        else:
            self.env.registry.clear_cache("assets")
