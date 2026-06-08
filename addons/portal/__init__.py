from odoo.tools.rendering_tools import template_env_globals
from odoo.http import request

# Expose `slug` to QWeb templates rendered outside a website context (mail
# bodies, portal pages). The lambda is required for late binding: `request`
# is a Werkzeug LocalProxy and `request.env` raises if accessed at import time.
template_env_globals.update(
    {
        "slug": lambda value: request.env["ir.http"]._slug(value)  # noqa: PLW0108 (lambda needed for late binding of `request`)
    }
)

from . import controllers
from . import models
from . import utils
from . import wizard
