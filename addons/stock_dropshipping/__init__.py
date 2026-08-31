from . import models


def uninstall_hook(env):
    env["stock.picking.type"].search([("code", "=", "dropship")]).active = False
