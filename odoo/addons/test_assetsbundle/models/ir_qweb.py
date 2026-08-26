from odoo import models
from odoo.tools import config

init = config["init"]


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _register_hook(self):
        super()._register_hook()
        registry = self.env.registry
        if init and registry.updated_modules and not registry.ready:
            # Regression coverage for install-time pregeneration itself
            # (odoo/modules/loading.py runs this during -i/-u, before the
            # registry is ready), not just the separate post-install-time
            # call that odoo/service/lifecycle.py makes for modules with
            # an HttpCase in their post_install suite. Both calls can run
            # for this addon (views.xml's bundle1/bundle4 are pulled in
            # via t-call-assets, and TestAssetsBundleInBrowser/
            # TestErrorManagement are post_install HttpCases), which is
            # expected: it is what proves pregeneration behaves the same
            # at both lifecycle points.
            self._pregenerate_assets_bundles()
