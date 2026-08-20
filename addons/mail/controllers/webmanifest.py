import re

from odoo.http import request
from odoo.tools import file_open

from odoo.addons.web.controllers import webmanifest

_ESM_EXPORT_RE = re.compile(
    r"^export\s+(?=(?:async\s+)?(?:const|let|var|function|class)\s)", re.MULTILINE
)


class WebManifest(webmanifest.WebManifest):
    def _get_service_worker_content(self) -> str:
        body = super()._get_service_worker_content()

        if request.env.user._is_internal():
            with file_open("mail/static/src/service_worker_utils.js") as f:
                utils = _ESM_EXPORT_RE.sub("", f.read())
            with file_open("mail/static/src/service_worker.js") as f:
                body += "\n" + utils + "\n" + f.read()

        return body
