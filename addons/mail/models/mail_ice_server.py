import datetime
import json
import logging

import requests

from odoo import fields, models

from odoo.addons.mail.tools.discuss import get_twilio_credentials

_logger = logging.getLogger(__name__)


class MailIceServer(models.Model):
    _name = "mail.ice.server"
    _description = "ICE Server"
    _rec_name = "uri"

    server_type = fields.Selection(
        [("stun", "stun:"), ("turn", "turn:")],
        string="Type",
        required=True,
        default="stun",
    )
    uri = fields.Char("URI", required=True)
    username = fields.Char()
    credential = fields.Char()

    def _get_local_ice_servers(self):
        """
        :return: List of up to 5 dict, each of which representing a stun or turn server
        """
        # firefox has a hard cap of 5 ice servers
        ice_servers = self.sudo().search([], limit=5)
        formatted_ice_servers = []
        for ice_server in ice_servers:
            formatted_ice_server = {
                "urls": "%s:%s" % (ice_server.server_type, ice_server.uri),
            }
            if ice_server.username:
                formatted_ice_server["username"] = ice_server.username
            if ice_server.credential:
                formatted_ice_server["credential"] = ice_server.credential
            formatted_ice_servers.append(formatted_ice_server)
        return formatted_ice_servers

    # Twilio TURN tokens are short-lived but reusable (default TTL 24h), so the
    # response is cached well under that. Without this, every RTC join did a
    # synchronous Twilio round-trip that could stall the join RPC (and its worker
    # thread) for the whole request timeout.
    _ICE_CACHE_TTL = 3600
    _ICE_CACHE_PARAM = "mail.ice_servers_cache"

    def _get_ice_servers(self):
        """
        :return: List of dict, each of which representing a stun or turn server,
                formatted as expected by the specifications of RTCConfiguration.iceServers
        """
        (account_sid, auth_token) = get_twilio_credentials(self.env)
        if not (account_sid and auth_token):
            return self._get_local_ice_servers()

        icp = self.env["ir.config_parameter"].sudo()
        now = self.env.cr.now()
        cached = icp.get_param(self._ICE_CACHE_PARAM)
        if cached:
            try:
                payload = json.loads(cached)
                if datetime.datetime.fromisoformat(payload["expiry"]) > now:
                    return payload["servers"]
            except ValueError, KeyError, TypeError:
                pass  # malformed / legacy cache: refetch below

        servers = self._fetch_twilio_ice_servers(account_sid, auth_token)
        if servers is None:
            return self._get_local_ice_servers()
        icp.set_param(
            self._ICE_CACHE_PARAM,
            json.dumps(
                {
                    "servers": servers,
                    "expiry": (
                        now + datetime.timedelta(seconds=self._ICE_CACHE_TTL)
                    ).isoformat(),
                }
            ),
        )
        return servers

    def _fetch_twilio_ice_servers(self, account_sid, auth_token):
        """Return Twilio's ICE server list, or None on any failure/timeout."""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Tokens.json"
        try:
            response = requests.post(url, auth=(account_sid, auth_token), timeout=5)
        except requests.RequestException:
            _logger.warning("Could not reach Twilio for TURN servers", exc_info=True)
            return None
        if response.ok:
            response_content = response.json()
            if response_content:
                return response_content["ice_servers"]
        else:
            _logger.warning(
                "Failed to obtain TURN servers, status code: %s, content:%s",
                response.status_code,
                response.content,
            )
        return None
