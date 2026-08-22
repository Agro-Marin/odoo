from odoo import api, models, tools
from odoo.http import request
from odoo.modules import Manifest

UNIT_TEST_ROUTES = ("/web/tests", "/web/bundle/")

UNIT_TEST_URL_SEGMENT = "scope"


class IrAsset(models.Model):
    _inherit = "ir.asset"

    def _prepare_assets_params(self):
        params = super()._prepare_assets_params()
        scope = self._get_unit_test_scope()
        if scope:
            params["unit_test_scope"] = scope
        return params

    @api.model
    def _get_unit_test_scope(self) -> str:
        if not request or not request.httprequest.path.startswith(UNIT_TEST_ROUTES):
            return ""
        scope = request.params.get("module_scope") or ""
        return scope if scope in self._get_addons_installed() else ""

    def _get_asset_bundle_url_segments(self, assets_params):
        segments = super()._get_asset_bundle_url_segments(assets_params)
        scope = assets_params.get("unit_test_scope")
        return (*segments, UNIT_TEST_URL_SEGMENT, scope) if scope else segments

    @api.model
    @tools.ormcache("scope")
    def _get_addons_in_unit_test_scope(self, scope: str) -> frozenset[str]:
        installed = self._get_addons_installed()
        closure: set[str] = set()
        todo = [scope]
        while todo:
            name = todo.pop()
            if name in closure or name not in installed:
                continue
            closure.add(name)
            todo.extend((Manifest.for_addon(name) or {}).get("depends") or ["base"])
        return frozenset(closure)

    def _get_addons_active(self, *, unit_test_scope=None, **params):
        addons_list = super()._get_addons_active(**params)

        if not unit_test_scope:
            return addons_list

        closure = self._get_addons_in_unit_test_scope(unit_test_scope)
        return [name for name in addons_list if name in closure]
