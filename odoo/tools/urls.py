import fnmatch
import urllib.parse

from odoo.libs.web import contains_dot_segments, urljoin, urls

# odoo.libs.web's own exports, plus the one helper defined here.  Named rather
# than star-imported so both a linter and a reader can see the surface;
# test_urls_keep_query pins this list against odoo.libs.web.__all__.
__all__ = [
    "contains_dot_segments",
    "keep_query",
    "urljoin",
    "urls",
]


def keep_query(*keep_params: str, **additional_params: object) -> str:
    """Re-emit the current request's query string, keeping `keep_params`.

    `odoo.http` is imported here rather than at module scope: tools sits below
    the serving tier, and odoo.http imports odoo.tools in eight places.  A
    module-level import made `import odoo.tools.urls` -- which ir_qweb and ~60
    other modules do, most of them only for `urljoin` -- load the whole HTTP
    stack.  `layer_check`'s `tools-stays-below-the-serving-tier` pins this.
    """
    from odoo.http import request

    if not keep_params and not additional_params:
        keep_params = ("*",)
    params = additional_params.copy()
    qs_keys = list(request.httprequest.args) if request else []
    for keep_param in keep_params:
        for param in fnmatch.filter(qs_keys, keep_param):
            if param not in additional_params:
                params[param] = request.httprequest.args.getlist(param)
    return urllib.parse.urlencode(params, doseq=True)
