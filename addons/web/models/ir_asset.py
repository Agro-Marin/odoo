# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, tools
from odoo.http import request
from odoo.modules import Manifest

#: Routes on which ``module_scope`` is honoured: the runner page, and the
#: bundle route the page's own ``loadBundle`` calls reach (the scope travels to
#: those through ``session_info['bundle_params']``). Both are answered by
#: resolving a bundle for the run, and neither is an ordinary page whose asset
#: cache a stray parameter could fragment.
UNIT_TEST_ROUTES = ("/web/tests", "/web/bundle/")

#: Marks the scope in an asset URL. A literal segment rather than a bare addon
#: name so the scoped route cannot shadow ``/web/assets/<unique>/<filename>``.
UNIT_TEST_URL_SEGMENT = "scope"


class IrAsset(models.Model):
    _inherit = "ir.asset"

    def _get_asset_params(self):
        params = super()._get_asset_params()
        scope = self._get_unit_test_scope()
        if scope:
            params["unit_test_scope"] = scope
        return params

    @api.model
    def _get_unit_test_scope(self) -> str:
        """Return the addon whose HOOT suite this request runs, else ``""``.

        ``web.assets_unit_tests_setup`` pulls in ``web.assets_backend``, so
        without a scope the unit-test page executes the ``src`` of EVERY
        installed addon. Those side effects are global and unconditional
        (registry entries, ``patch()`` calls), while mock models are opt-in per
        suite via ``defineModels()`` — so one addon's ``src`` routinely reaches
        for a model that another addon's suite never defined, and the mock
        server can only answer with "Cannot find a definition for model X".
        Scoping the bundle to the suite's own dependency closure removes the
        asymmetry at its source: what cannot load cannot register.

        Read from the request rather than the bundle because the scope varies
        per run, not per bundle definition. Only honoured on the runner routes,
        so a stray ``module_scope`` elsewhere cannot fragment the asset cache
        of ordinary pages, and only for an installed addon, so the number of
        variants it can mint is bounded by the addons on disk.

        The bundle the runner page *links* is covered by the URL it was
        published under (:meth:`_get_asset_url_segments`); this covers the ones
        the page asks for afterwards.
        """
        if not request or not request.httprequest.path.startswith(UNIT_TEST_ROUTES):
            return ""
        scope = request.params.get("module_scope") or ""
        return scope if scope in self._get_installed_addons_list() else ""

    def _get_asset_url_segments(self, assets_params):
        """Name the scope, so ``content_assets_scoped`` can rebuild the bundle.

        Without it a scoped bundle is published under a URL that differs from
        the unscoped one only by ``unique`` -- distinct, but not rebuildable,
        because ``content_assets`` re-resolves from the URL alone. The scoped
        CSS then 303'd to the unscoped bundle on every runner page load, which
        is precisely the foreign content the scope exists to keep out.
        """
        segments = super()._get_asset_url_segments(assets_params)
        scope = assets_params.get("unit_test_scope")
        return (*segments, UNIT_TEST_URL_SEGMENT, scope) if scope else segments

    @api.model
    @tools.ormcache("scope")
    def _get_unit_test_scope_addons(self, scope: str) -> frozenset[str]:
        """Return ``scope`` plus its transitive manifest dependencies.

        The manifest graph is the right closure even though it looks too
        narrow: ``mail`` declares only ``web_tour`` and ``html_editor``, but
        ``html_editor`` → ``bus`` → ``web`` → ``base``, so everything its JS
        actually needs is pulled in. Addons outside the closure are exactly the
        ones whose ``src`` a correct suite must not depend on.
        """
        installed = self._get_installed_addons_list()
        closure: set[str] = set()
        todo = [scope]
        while todo:
            name = todo.pop()
            if name in closure or name not in installed:
                continue
            closure.add(name)
            todo.extend((Manifest.for_addon(name) or {}).get("depends") or ["base"])
        return frozenset(closure)

    def _get_active_addons_list(self, *, unit_test_scope=None, **params):
        """Overridden to narrow the bundle to a HOOT suite's dependency closure."""
        addons_list = super()._get_active_addons_list(**params)

        if not unit_test_scope:
            return addons_list

        closure = self._get_unit_test_scope_addons(unit_test_scope)
        return [name for name in addons_list if name in closure]
