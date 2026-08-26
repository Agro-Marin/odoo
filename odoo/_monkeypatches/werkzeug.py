from werkzeug.wrappers import Request, Response


def patch_module() -> None:
    """Serialize werkzeug's JSON through Odoo's script-safe encoder.

    `Request.json_module`/`Response.json_module` default to the stdlib `json`,
    which happily emits `</script>` and `<!--` verbatim. Any JSON embedded in
    an HTML document can then close the tag that contains it, so the payload
    becomes markup. `odoo.libs.json.scriptsafe` escapes those sequences.

    Imported inside the function on purpose: `odoo.libs.json` is Odoo code, and
    importing it at module scope would make this patch module depend on a
    package that is still being set up when the patches are applied.
    """
    from odoo.libs.json import scriptsafe

    Request.json_module = Response.json_module = scriptsafe
