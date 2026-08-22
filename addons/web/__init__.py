from odoo.http import register_ensure_db_paths

from . import controllers
from . import models

register_ensure_db_paths("/odoo", "/web", "/web/login", prefixes=("/odoo/",))
