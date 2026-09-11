from . import models
from . import wizards


def uninstall_hook(env):
    env["loyalty.history"].search([("order_model", "=", "sale.order")]).unlink()
