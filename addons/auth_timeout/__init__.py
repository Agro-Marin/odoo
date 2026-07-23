from odoo.http import register_routing_parameters

# ``check_identity`` is set only by this module's own controllers and read by
# its ir_http (re-authentication gate) — a genuinely module-local @route key,
# declared before the controllers that use it are imported. (The website/
# http_routing vocabulary lives core-side instead — see
# odoo.http.routing._KNOWN_ROUTING_PARAMETERS for why.)
register_routing_parameters("check_identity")

from . import controllers
from . import models
