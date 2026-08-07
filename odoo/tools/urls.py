"""URL utilities for Odoo web framework."""

import fnmatch
import urllib.parse

from odoo.http import request
from odoo.libs.web import *


def keep_query(*keep_params: str, **additional_params: object) -> str:
    """Generate a query string keeping current request parameters.

    Keeps querystring parameters listed in ``keep_params`` (wildcards
    allowed, e.g. ``keep_query("search", "shop_*", page=4)``) and adds
    ``additional_params``. Parameters with multiple values are kept as
    repeated params.
    """
    if not keep_params and not additional_params:
        keep_params = ("*",)
    params = additional_params.copy()
    qs_keys = list(request.httprequest.args) if request else []
    for keep_param in keep_params:
        for param in fnmatch.filter(qs_keys, keep_param):
            if param not in additional_params:
                params[param] = request.httprequest.args.getlist(param)
    return urllib.parse.urlencode(params, doseq=True)
