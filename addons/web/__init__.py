from odoo.http import register_ensure_db_paths

from . import controllers
from . import models

# Served db-less when a registry fails, so the user reaches the database
# selector instead of a 500 (see odoo.http.register_ensure_db_paths).
register_ensure_db_paths("/odoo", "/web", "/web/login", prefixes=("/odoo/",))
