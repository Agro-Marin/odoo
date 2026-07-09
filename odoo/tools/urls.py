"""URL utilities for Odoo web framework."""

import fnmatch
import urllib.parse

from odoo.http import request

# Re-export from canonical location
from odoo.libs.web.urls import *  # noqa: F403
from odoo.libs.web.urls import (
    _contains_dot_segments,  # noqa: F401 — used by website.models.website
)


def keep_query(*keep_params: str, **additional_params: object) -> str:
    """Generate a query string keeping current request parameters.

    Keeps the current request querystring's parameters specified
    in ``keep_params`` and also adds the parameters specified in
    ``additional_params``.

    Query-string parameters with multiple values are kept as repeated
    parameters.

    The ``keep_params`` arguments can use wildcards too, eg::

        keep_query("search", "shop_*", page=4)
    """
    if not keep_params and not additional_params:
        keep_params = ("*",)
    params = additional_params.copy()
    qs_keys = list(request.httprequest.args) if request else []
    for keep_param in keep_params:
        for param in fnmatch.filter(qs_keys, keep_param):
            # ``param`` comes from ``fnmatch.filter(qs_keys, ...)``, so it is
            # always in ``qs_keys`` -- the only real check is the override guard.
            if param not in additional_params:
                params[param] = request.httprequest.args.getlist(param)
    return urllib.parse.urlencode(params, doseq=True)
