import logging

from odoo.http import Controller, dispatch_rpc, route

from .common import detach_database, warn_endpoint_is_deprecated

logger = logging.getLogger(__name__)


class JSONRPC(Controller):
    @route("/jsonrpc", type="jsonrpc", auth="none", save_session=False)
    def jsonrpc(self, service, method, args):
        """Method used by client APIs to contact Odoo."""
        warn_endpoint_is_deprecated(logger, __name__)
        detach_database()
        return dispatch_rpc(service, method, args)
