from odoo.addons.api_transport.tools import shutdown_event_queue

from . import controllers, models, tools
from .hooks import post_init_hook, pre_init_hook

__all__ = ["post_init_hook", "pre_init_hook", "uninstall_hook"]


def uninstall_hook(env):
    """Clean up the event queue and related resources on uninstall.

    :param env: Odoo environment with SUPERUSER_ID context
    """
    shutdown_event_queue()
