from . import models


def uninstall_hook(env):
    # Uninstalling the module will archive the dropshipping picking type.
    env['stock.picking.type'].search([('code', '=', 'dropship')]).active = False
