from odoo import models
from odoo.http import SessionExpiredException
from odoo.service import security
from odoo.tools.misc import OrderedSet

from ..models.bus import dispatch
from ..websocket import wsrequest

# Upper bounds on a single subscription, see ``_prepare_subscribe_data``.
#
# Deliberately far above any plausible client rather than close to it. Crossing
# the limit rejects the whole subscribe message, and while that does not close
# the connection (``_serve_forever`` logs client-controlled ValueErrors and
# carries on), the tab keeps whatever subscription it had until something
# triggers a re-subscribe -- so a limit tight enough to catch a real user would
# cost them bus delivery for a reason only a server log explains. The channels
# counted here are the client-supplied ones only; the groups and partner channel
# that ``_build_bus_channel_list`` adds afterwards are not, so a user in many
# groups is unaffected. Discuss is the heaviest known caller (one presence
# channel per monitored partner, plus one per non-member thread) and stays
# orders of magnitude below this.
#
# 4096 channels still bounds the amplification that motivated the cap to a few
# MiB per connection: 20 000 channels measured at ~21 MiB, and it is linear.
MAX_SUBSCRIBED_CHANNELS = 4096
# Comfortably above the longest real names: presence channels
# (``odoo-presence-res.partner_<id>-<64 hex>o0x<hex>``) run to about 100
# characters, access-token channels to well under that.
MAX_CHANNEL_LENGTH = 512


class IrWebsocket(models.AbstractModel):
    _name = "ir.websocket"
    _description = "websocket message handling"

    def _build_bus_channel_list(self, channels):
        """
        Return the list of channels to subscribe to. Override this
        method to add channels in addition to the ones the client
        sent.

        :param channels: The channel list sent by the client.
        """
        channels = [*channels, "broadcast", *self.env.user.all_group_ids]
        # Add the personal channel only for a genuinely logged-in user. This
        # used to read ``(request or wsrequest).session.uid``, which made a
        # plain model method depend on whichever of two ambient request
        # globals happened to be bound -- so it could not be called from a
        # test, a cron or a shell without faking a request. ``env.user`` is
        # already the authoritative answer here: ``ir.websocket._authenticate``
        # binds the public user precisely when ``session.uid`` is None, so the
        # two predicates agree on every reachable path (verified over the
        # authenticated/anonymous × websocket/HTTP matrix).
        if not self.env.user._is_public():
            channels = [*channels, self.env.user.partner_id]
        return channels

    def _serve_ir_websocket(self, event_name, data):
        """Process websocket events.
        Modules can override this method to handle their own events. But overriding this method is
        not recommended and should be carefully considered, because at the time of writing this
        message, Odoo.sh does not use this method. Each new event should have a corresponding http
        route and Odoo.sh infrastructure should be updated to reflect it. On top of that, the
        event processing is very time, ressource and error sensitive."""

    def _prepare_subscribe_data(self, channels, last):
        """
        Parse the data sent by the client and return the list of channels
        and the last known notification id. This will be used both by the
        websocket controller and the websocket request class when the
        `subscribe` event is received.

        :param typing.List[str] channels: List of channels to subscribe to sent
            by the client.
        :param int last: Last known notification sent by the client.

        :return:
            A dict containing the following keys:
            - channels (set of str): The list of channels to subscribe to.
            - last (int): The last known notification id.

        :raise ValueError: If the arguments do not have the expected
            types/shape. Both the websocket `subscribe` event and the
            `/websocket/peek_notifications` route feed this method raw
            client-controlled data, so validation must not assume anything.
        """
        if not isinstance(channels, (list, tuple)) or not all(
            isinstance(c, str) for c in channels
        ):
            raise ValueError("bus.Bus only string channels are allowed.")
        # Bound the subscription itself. Only the 1 MiB frame cap used to limit
        # it, and a subscribe is worth far more than it costs to send: measured,
        # 20 000 channels arrive in an 859 KiB frame and retain ~21 MiB of server
        # memory for as long as the (possibly anonymous) connection lives -- ~24
        # bytes held per byte on the wire, sustainable at ~1 MiB/s without
        # tripping the rate limiter. The memory is released on disconnect, so
        # this is amplification rather than a leak, but nothing capped it.
        if len(channels) > MAX_SUBSCRIBED_CHANNELS:
            raise ValueError(
                f"bus.Bus subscription is limited to {MAX_SUBSCRIBED_CHANNELS} "
                f"channels, got {len(channels)}."
            )
        if any(len(channel) > MAX_CHANNEL_LENGTH for channel in channels):
            raise ValueError(
                f"bus.Bus channel names are limited to {MAX_CHANNEL_LENGTH} characters."
            )
        if not isinstance(last, int) or isinstance(last, bool):
            raise ValueError("bus.Bus subscription 'last' must be an integer.")
        # Clamp to [0, max_id]: negative values would match all rows, values
        # beyond max_id skip all existing notifications (reset to 0 instead).
        last = max(0, last)
        if last:
            # Only when there is something to clamp. ``last == 0`` already means
            # "start from the lookback window", and ``0 > max_id`` can never hold
            # (ids are positive, the aggregate coalesces to 0), so the query was
            # pure overhead on the commonest subscribe of all -- and subscribes
            # are frequent, the worker re-sends one on every channel change.
            # sudo - bus.bus: reading non-sensitive last bus id.
            last = 0 if last > self.env["bus.bus"].sudo()._bus_last_id() else last
        channels = [c for c in channels if self._is_subscribable_channel(c)]
        return {
            "channels": OrderedSet(self._build_bus_channel_list(list(channels))),
            "last": last,
        }

    def _is_subscribable_channel(self, channel):
        """Whether the caller may subscribe to this client-supplied channel name.

        Accepts everything by default, which is the historical behaviour and what
        every current caller relies on. It exists so that behaviour has a single
        place to change: ``/websocket`` is ``auth="public"``, so any client --
        including an unauthenticated one -- may subscribe to any string channel
        and receive everything ``bus.bus._sendone`` publishes there. Verified
        against a running server: a socket with no session cookie subscribed to a
        plausibly-named channel and received its payload in full.

        The exposure is bounded to *string* channels. Record-derived channels are
        unreachable from client input, because ``channel_with_db`` only ever turns
        a client string into a two-element key, never the three-element one a
        record produces. So the callers at risk are exactly those passing a bare
        string to ``_sendone``, whose sole protection today is that the name is
        hard to guess (as ``_sendone``'s own docstring asks). Override here to
        enforce that centrally instead of trusting each caller.
        """
        return True

    def _after_subscribe_data(self, data):
        """Function invoked after subscribe data have been processed.
        Modules can override this method to add custom behavior."""

    def _subscribe(self, og_data):
        if not isinstance(og_data, dict) or "channels" not in og_data:
            raise ValueError(
                "bus.Bus subscribe data must be a dict with a 'channels' key."
            )
        data = self._prepare_subscribe_data(og_data["channels"], og_data.get("last", 0))
        dispatch.subscribe(
            data["channels"], data["last"], self.env.registry.db_name, wsrequest.ws
        )
        self._after_subscribe_data(data)

    def _on_websocket_closed(self, cookies):
        """Function invoked upon WebSocket termination.
        Modules can override this method to add custom behavior."""

    def _authenticate(self):
        """Bind the websocket request's environment to its authenticated user.

        An ordinary method, not a classmethod: it is reached as
        ``self.env["ir.websocket"]._authenticate()`` and overrides are entitled
        to ``self.env`` like anywhere else in the ORM. ``wsrequest`` is still
        used for what genuinely belongs to the request (the session, and
        rebinding its env), but never as a substitute for ``self.env``.
        """
        if wsrequest.session.uid is not None:
            if not security.check_session(wsrequest.session, self.env, wsrequest):
                wsrequest.session.logout(keep_db=True)
                raise SessionExpiredException
        else:
            # `_xmlid_to_res_id`, not `env.ref`: only the id is wanted, and
            # `Environment.ref` additionally runs an `exists()` query whose
            # `transaction._ref_cache` can never help here -- every websocket
            # message is served on a fresh cursor, hence a fresh transaction.
            # Traced: exactly one such query per message on every public
            # connection, ten for ten messages. `_xmlid_to_res_id` is ormcached
            # and raises the same way when the xmlid is genuinely absent.
            public_user_id = self.env["ir.model.data"]._xmlid_to_res_id(
                "base.public_user"
            )
            wsrequest.update_env(user=public_user_id)
