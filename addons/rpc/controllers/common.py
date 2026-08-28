import logging

from odoo.http import request

RPC_DEPRECATION_NOTICE = """\
The /xmlrpc, /xmlrpc/2 and /jsonrpc endpoints are deprecated in Odoo 19 \
and scheduled for removal in Odoo 20. Please report the problem to the \
client making the request: %s, %s.
Mute this logger: --log-handler %s:ERROR
https://www.odoo.com/documentation/latest/developer/reference/external_api.html#migrating-from-xml-rpc-json-rpc"""

# One notice per client per process, not one per call. The notice names no
# request, so repeating it told an operator nothing a second time -- and it was
# measured at 645 bytes of log per RPC call, which an integration polling
# `/xmlrpc/2/object` turns into tens of megabytes a day of one repeated
# paragraph. Keyed by caller instead, it says what the notice actually asks for
# ("report the problem to the client making the request") and could not say
# before: which client, and what it calls itself.
_WARNED_CLIENTS: set[tuple[str, str, str]] = set()

# The keys come from the network, so the set is bounded rather than trusted; a
# caller rotating its address or user-agent cannot grow it without limit. Past
# the cap the point has been made and nothing more is logged.
_WARNED_CLIENTS_LIMIT = 64


def warn_endpoint_is_deprecated(logger: logging.Logger, module: str) -> None:
    client = request.httprequest.remote_addr or "unknown"
    agent = request.httprequest.user_agent.string or "no user-agent"
    # The user-agent is part of the key, not decoration. Odoo only rewrites
    # `remote_addr` from `X-Forwarded-For` when `proxy_mode` is on, which is
    # off by default: behind a reverse proxy every caller shares one address,
    # and keying on the address alone would name the first integration to call
    # and silence every other one. Distinct clients almost always send distinct
    # user-agents, so the pair separates them where the address cannot.
    key = (module, client, agent)
    if key in _WARNED_CLIENTS or len(_WARNED_CLIENTS) >= _WARNED_CLIENTS_LIMIT:
        return
    _WARNED_CLIENTS.add(key)
    logger.warning(RPC_DEPRECATION_NOTICE, client, agent, module)


def detach_database() -> None:
    """Declare that this handler resolves its own database.

    An RPC caller names the database in its payload, so the request must not
    stay bound to the one the dbfilter picked for it.
    """
    if request.db:
        request.detach_database()
