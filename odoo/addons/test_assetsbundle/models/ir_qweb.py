from odoo import models
from odoo.tools import config

init = config["init"]


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _register_hook(self):
        super()._register_hook()
        # This module being installed means we are in a test environment -- on
        # runbot especially, where every module is. Building the bundles once at
        # the end of loading is cheaper than letting the first test of each
        # HttpCase pay for them.
        #
        # NB the cost lands on the whole install, not on this module: the
        # condition is `-i <anything>`, so `-i some_unrelated_module` against a
        # database that happens to carry test_assetsbundle pregenerates every
        # bundle too (measured at ~6s on a base+web database). odoo/service/
        # lifecycle.py already pregenerates before the post_install suite when
        # it holds an HttpCase, so what remains here is the at_install half.
        registry = self.env.registry
        if init and registry.updated_modules and not registry.ready:
            self._pregenerate_assets_bundles()
