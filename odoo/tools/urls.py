import fnmatch
import urllib.parse

from odoo.libs.web import contains_dot_segments, urljoin, urls

__all__ = [
    "contains_dot_segments",
    "keep_query",
    "urljoin",
    "urls",
]


def keep_query(*keep_params: str, **additional_params: object) -> str:
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
