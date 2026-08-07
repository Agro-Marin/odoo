import fnmatch
import urllib.parse

from odoo.http import request
from odoo.libs.web import *  # noqa: F403  re-export shim, bounded by odoo.libs.web.__all__


def keep_query(*keep_params: str, **additional_params: object) -> str:
    if not keep_params and not additional_params:
        keep_params = ("*",)
    params = additional_params.copy()
    qs_keys = list(request.httprequest.args) if request else []
    for keep_param in keep_params:
        for param in fnmatch.filter(qs_keys, keep_param):
            if param not in additional_params:
                params[param] = request.httprequest.args.getlist(param)
    return urllib.parse.urlencode(params, doseq=True)
