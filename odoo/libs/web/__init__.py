"""Odoo-agnostic web utilities.

Pure Python web helpers with no Odoo dependencies.

The public boundary of this area is the package, not its modules: import
``urljoin`` / ``import_map_for`` from ``odoo.libs.web``, not from
``odoo.libs.web.urls`` / ``odoo.libs.web.import_map``. The submodules stay
exported for callers that need the module object itself.
"""

from . import import_map, urls
from .import_map import ImportMap, import_map_for
from .urls import urljoin

__all__ = [
    "ImportMap",
    "import_map",
    "import_map_for",
    "urljoin",
    "urls",
]
