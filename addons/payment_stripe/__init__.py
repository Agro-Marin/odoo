from . import controllers
from . import models

from odoo.addons import payment  # prevent circular import error with payment


def post_init_hook(env):
    payment.setup_provider(env, "stripe")


def uninstall_hook(env):
    payment.reset_payment_provider(env, "stripe")
