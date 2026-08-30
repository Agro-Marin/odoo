import base64
import hashlib
from typing import NamedTuple

from odoo.libs.json import scriptsafe
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
    # scriptsafe, not json.dumps: this JSON is embedded in a <script> element,
    # and the HTML parser ends that element at the first `</script`, whatever
    # the JSON grammar thinks. json.dumps escapes `"` and `\` and leaves `<`
    # and `/` alone, so a URL or specifier carrying `</script>` would close the
    # tag and everything after it would be markup. The values come from the
    # `esm.external_libs` manifest key -- developer input in a checkout, and
    # admin input once base_import_module is in play.
    #
    # `__html__()` is where ScriptSafe applies the mapping; str() of it does
    # not. The hash is taken over the ESCAPED text because that is what the
    # browser hashes: a CSP script hash covers the element's literal content,
    # not the JSON it decodes to.
    body = str(scriptsafe.dumps({"imports": imports}, separators=(",", ":")).__html__())
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return ImportMap(
        script_tag=f'<script type="importmap">{body}</script>',
        csp_hash=f"'sha256-{digest}'",
    )
