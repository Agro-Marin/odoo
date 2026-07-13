# ruff: noqa: F401
"""Bus module JSON serialization — delegates to the centralized orjson wrapper.

Compatibility shim kept only for ``odoo.addons.bus.websocket``; new code
should import from :mod:`odoo.libs.json` directly (note that ``dumps`` here is
``dumps_bytes``, i.e. it returns ``bytes``, unlike ``odoo.libs.json.dumps``).
"""

from odoo.libs.json.orjson_wrapper import dumps_bytes as dumps
from odoo.libs.json.orjson_wrapper import loads
