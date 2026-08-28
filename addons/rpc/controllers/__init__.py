import odoo.release
from odoo.http import request, route

from . import common, json2
from .jsonrpc import JSONRPC
from .xmlrpc import XMLRPC


class RPC(XMLRPC, JSONRPC):
    @route(["/web/version", "/json/version"], type="http", auth="none", readonly=True)
    def version(self):
        return request.make_json_response(
            {
                "version_info": odoo.release.version_info,
                "version": odoo.release.version,
            }
        )
