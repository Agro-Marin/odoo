import base64
import hashlib
import json
from typing import NamedTuple

from odoo.tools.assets.esm_registry import external_libs

__all__ = ["ImportMap", "import_map_for"]


class ImportMap(NamedTuple):
    script_tag: str
    csp_hash: str


def import_map_for(*specifiers: str) -> ImportMap:
    registered = external_libs()
    unknown = sorted(set(specifiers) - set(registered))
    if unknown:
        msg = (
            f"unknown external lib specifier(s): {', '.join(unknown)}. "
            f"Declare them under the 'esm.external_libs' key of the manifest "
            f"of the module that ships them."
        )
        raise KeyError(msg)

    imports = {spec: registered[spec] for spec in sorted(set(specifiers))}
    body = json.dumps({"imports": imports}, separators=(",", ":"))
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return ImportMap(
        script_tag=f'<script type="importmap">{body}</script>',
        csp_hash=f"'sha256-{digest}'",
    )
