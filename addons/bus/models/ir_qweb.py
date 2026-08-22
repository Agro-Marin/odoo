from odoo import models

WORKER_BUNDLE = "bus.websocket_worker_assets"


class IrQWeb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_websocket_worker_bundle(self):
        """Build (or reuse) the self-contained websocket worker bundle.

        The worker graph (``bus/static/src/workers/*``) must be delivered as a
        SINGLE file: the cross-origin path in ``worker_service.js`` boots the
        worker from a ``blob:`` URL, and module workers cannot resolve relative
        imports against a blob URL. That is what ``esm.standalone_bundles``
        declares and what ``_get_standalone_bundle`` builds.

        :return: an ``(url, code)`` tuple, or ``None`` when the build declined
            (circuit breaker open, lock contention, esbuild failure, ...).
            Callers degrade to the raw entry file in that case.
        """
        return self._get_standalone_bundle(WORKER_BUNDLE)

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
