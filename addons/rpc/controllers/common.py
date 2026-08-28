import logging

from odoo.http import request

RPC_DEPRECATION_NOTICE = """\
The /xmlrpc, /xmlrpc/2 and /jsonrpc endpoints are deprecated in Odoo 19 \
and scheduled for removal in Odoo 20. Please report the problem to the \
client making the request: %s, %s.
Mute this logger: --log-handler %s:ERROR
https://www.odoo.com/documentation/latest/developer/reference/external_api.html#migrating-from-xml-rpc-json-rpc"""

_WARNED_CLIENTS: set[tuple[str, str, str]] = set()

_WARNED_CLIENTS_LIMIT = 64


def warn_endpoint_is_deprecated(logger: logging.Logger, module: str) -> None:
    client = request.httprequest.remote_addr or "unknown"
    agent = request.httprequest.user_agent.string or "no user-agent"
    key = (module, client, agent)
    if key in _WARNED_CLIENTS or len(_WARNED_CLIENTS) >= _WARNED_CLIENTS_LIMIT:
        return
    _WARNED_CLIENTS.add(key)
    logger.warning(RPC_DEPRECATION_NOTICE, client, agent, module)


def detach_database() -> None:
    if request.db:
        request.detach_database()
