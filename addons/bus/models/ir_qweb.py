import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)

WORKER_BUNDLE = "bus.websocket_worker_assets"


class _WorkerBundleDeclined(Exception):
    """Signal that the worker-bundle build declined, so the ormcache never
    stores the degraded (None) result — same pattern as ``_EsmFallbackError``
    in the native-ESM render path."""


class IrQWeb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_websocket_worker_bundle(self):
        """Build (or reuse) the self-contained websocket worker bundle.

        The worker graph (``bus/static/src/workers/*``) must be delivered as a
        SINGLE file: the cross-origin path in ``worker_service.js`` boots the
        worker from a ``blob:`` URL, and module workers cannot resolve relative
        imports against a blob URL. Compile it through the regular esbuild
        pipeline (standalone mode — no page-context glue) and persist it as a
        content-addressed ``/web/assets/esm/<hash>/...`` attachment.

        :return: an ``(url, code)`` tuple, or ``None`` when the build declined
            (circuit breaker open, lock contention, esbuild failure, ...).
            Callers degrade to the raw entry file in that case.

        The compiled code is returned alongside the URL on purpose: the
        attachment row is committed out of band on a dedicated cursor
        (see ``_persist_esm_attachment_rows``), so the *current* request's
        repeatable-read transaction cannot see it yet — the serving
        controller must not need a row lookup.
        """
        try:
            return self._get_websocket_worker_bundle_cached()
        except _WorkerBundleDeclined:
            return None

    @tools.conditional(
        # Mirror the native-ESM node caches: cache until ir.asset writes /
        # module update clear the "assets" cache (a new build saves a new
        # content-addressed attachment and clears it too).
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(cache="assets"),
    )
    def _get_websocket_worker_bundle_cached(self):
        assets_params = self.env["ir.asset"]._get_asset_params()
        asset_bundle = self._get_asset_bundle(
            WORKER_BUNDLE, css=False, assets_params=assets_params
        )
        esbuild_result, _child_bundles = self._esm_run_esbuild(
            WORKER_BUNDLE, asset_bundle, assets_params
        )
        if not esbuild_result.code:
            raise _WorkerBundleDeclined
        try:
            url = self._save_esm_attachment(
                WORKER_BUNDLE,
                esbuild_result.code,
                metafile=esbuild_result.metafile,
                sourcemap=esbuild_result.sourcemap,
            )
        except Exception as exc:
            # Same degradation contract as the render path: a persistence
            # failure (read-only cursor with the primary unreachable, ...)
            # must not break the endpoint — the controller falls back to the
            # raw entry file, which works for same-origin workers.
            _logger.warning(
                "Could not persist the websocket worker bundle", exc_info=True
            )
            raise _WorkerBundleDeclined from exc
        return url, esbuild_result.code

    def _pregenerate_assets_bundles(self):
        """Also pregenerate the websocket worker bundle.

        It is not referenced by any ``t-call-assets`` (it is fetched by
        ``worker_service.js`` through ``/bus/websocket_worker_bundle``), so the
        generic view scan cannot discover it. The previous approach — adding it
        to ``_get_bundles_to_pregenerate`` — built it as a LEGACY bundle, which
        the module-syntax guard rejects file by file now that the workers are
        native ESM.
        """
        links = super()._pregenerate_assets_bundles()
        result = self._get_websocket_worker_bundle()
        if result:
            links.append(result[0])
        return links
