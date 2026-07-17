import re

from odoo.http import request
from odoo.tools import file_open

from odoo.addons.web.controllers import webmanifest

# The push worker's pure helpers live in an ESM module (unit-tested under hoot).
# The service worker is served as a classic worker (raw concatenated text, no
# module system), so the module's ESM `export` keyword is stripped before it is
# inlined ahead of the worker that calls the helpers as plain globals.
_ESM_EXPORT_RE = re.compile(r"^export\s+", re.MULTILINE)


class WebManifest(webmanifest.WebManifest):
    def _get_service_worker_content(self):
        body = super()._get_service_worker_content()

        # Add notification support to the service worker if user but no public
        if request.env.user._is_internal():
            with file_open("mail/static/src/service_worker_utils.js") as f:
                utils = _ESM_EXPORT_RE.sub("", f.read())
            with file_open("mail/static/src/service_worker.js") as f:
                body += "\n" + utils + "\n" + f.read()

        return body
