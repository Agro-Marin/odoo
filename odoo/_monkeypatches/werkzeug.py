from werkzeug.wrappers import Request, Response


def patch_module() -> None:
    from odoo.libs.json import scriptsafe

    Request.json_module = Response.json_module = scriptsafe
