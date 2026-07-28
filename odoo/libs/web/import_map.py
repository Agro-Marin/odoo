"""Import-map emission paired with the CSP source expression that admits it.

A ``<script type="importmap">`` is an *inline* script.  Under a policy whose
``script-src`` omits ``'unsafe-inline'`` the browser refuses it, the map never
registers, and every bare specifier on the page fails to resolve — with no
server-side symptom whatsoever.  Deriving the tag and its ``'sha256-…'``
expression from the same bytes keeps the document and the policy guarding it in
agreement by construction, so neither can drift out from under the other.

Standalone pages (the IoT box homepage, the database manager, the error page)
live outside the asset pipeline and so cannot use the import map that
``ir.qweb`` emits for the webclient.  They still resolve their specifiers
through :data:`~odoo.libs.constants.ODOO_EXTERNAL_LIBS`, which stays the single
registry of vendored-library URLs.
"""

import base64
import hashlib
import json
from typing import NamedTuple

from odoo.libs.constants import ODOO_EXTERNAL_LIBS

__all__ = ["ImportMap", "import_map_for"]


class ImportMap(NamedTuple):
    """An import map and the CSP ``script-src`` expression that allows it."""

    script_tag: str
    csp_hash: str


def import_map_for(*specifiers: str) -> ImportMap:
    """Build the import map exposing ``specifiers`` to a standalone page.

    :param specifiers: bare specifiers to expose, e.g. ``"@popperjs/core"``.
        Each must be registered in ``ODOO_EXTERNAL_LIBS``.
    :raises KeyError: if a specifier is not a known external lib.
    """
    unknown = sorted(set(specifiers) - set(ODOO_EXTERNAL_LIBS))
    if unknown:
        msg = (
            f"unknown external lib specifier(s): {', '.join(unknown)}. "
            f"Register them in odoo.libs.constants.ODOO_EXTERNAL_LIBS first."
        )
        raise KeyError(msg)

    imports = {spec: ODOO_EXTERNAL_LIBS[spec] for spec in sorted(set(specifiers))}
    body = json.dumps({"imports": imports}, separators=(",", ":"))
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return ImportMap(
        script_tag=f'<script type="importmap">{body}</script>',
        csp_hash=f"'sha256-{digest}'",
    )
