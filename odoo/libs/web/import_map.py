import base64
import hashlib
import json
from typing import NamedTuple

from odoo.libs.constants import ODOO_EXTERNAL_LIBS

__all__ = ["ImportMap", "import_map_for"]


class ImportMap(NamedTuple):
    script_tag: str
    csp_hash: str


def import_map_for(*specifiers: str) -> ImportMap:
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
