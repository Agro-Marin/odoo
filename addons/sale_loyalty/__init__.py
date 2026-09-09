from . import models
from . import wizard


def uninstall_hook(env):
    env["loyalty.history"].search([("order_model", "=", "sale.order")]).unlink()
