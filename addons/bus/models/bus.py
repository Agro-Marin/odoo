import contextlib
import datetime
import logging
import os
import selectors
import threading
import time

import psycopg
import psycopg.sql
from psycopg import InterfaceError

import odoo
from odoo import api, fields, models
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.service.server import CommonServer
from odoo.tools import SQL
from odoo.tools.json import orjson_default
from odoo.tools.misc import OrderedSet

_logger = logging.getLogger(__name__)

# How far back ``_poll`` looks when the client has no last notification id.
# A client that connects without a watermark gets whatever landed in this
# window; anything older is considered already-missed and is left to the
# outdated-page watcher. Unrelated to the two dispatcher timings below --
# these three used to share a single ``TIMEOUT = 50`` constant (named after
# the long-polling transport that no longer exists), so tuning the poll
# window silently changed the dispatcher's retry ceiling.
POLL_LOOKBACK_SECONDS = 50
# How long ``ImDispatch.loop`` blocks in ``select()`` before looping back to
# re-check ``stop_event``. Bounds how long a shutdown waits on an idle
# dispatcher, nothing else.
DISPATCHER_SELECT_TIMEOUT = 50
# Ceiling of the exponential backoff between ``ImDispatch.loop`` restarts, and
# the "the loop stayed up long enough to count as a new incident" threshold.
MAX_DISPATCHER_RETRY_DELAY = 50
DEFAULT_GC_RETENTION_SECONDS = 60 * 60 * 24  # 24 hours
# How long a websocket holds its low-water-mark notification id back so that
# notifications committed out of id order by concurrent transactions are not
# skipped. Defined here rather than in ``websocket.py`` because both ends of
# the contract need it: the receiving side sizes its hold-back window with it
# (``Websocket.MAX_NOTIFICATION_HISTORY_SEC``), and the sending side uses it
# to warn when a transaction is at risk of falling outside that window (see
# ``_ensure_hooks``). Two literals would silently drift apart.
NOTIFICATION_HOLD_BACK_SECONDS = 10

# custom function to call instead of default PostgreSQL's `pg_notify`
ODOO_NOTIFY_FUNCTION = os.getenv("ODOO_NOTIFY_FUNCTION", "pg_notify")


def get_notify_payload_max_length(default=8000):
    try:
        length = int(os.environ.get("ODOO_NOTIFY_PAYLOAD_MAX_LENGTH", default))
    except ValueError:
        _logger.warning(
            "ODOO_NOTIFY_PAYLOAD_MAX_LENGTH has to be an integer, "
            "defaulting to %d bytes",
            default,
        )
        length = default
    return length


# max length in bytes for the NOTIFY query payload
NOTIFY_PAYLOAD_MAX_LENGTH = get_notify_payload_max_length()

# Number of websockets woken per batch, and pause between batches, when
# catching up after a LISTEN reconnect (see ImDispatch._dispatch_to_all).
DISPATCH_CATCHUP_CHUNK_SIZE = 50
DISPATCH_CATCHUP_CHUNK_DELAY = 0.1  # seconds

# Hard bounds on what a single ``_poll`` may return.
#
# A client reconnects with the last notification id it saw, and ``bus_bus``
# retains a whole ``DEFAULT_GC_RETENTION_SECONDS`` window, so an unbounded
# ``id > last`` returns the entire backlog of a busy channel in one go. The
# resulting frame is one the serving thread cannot finish writing:
# ``Websocket.FRAME_RECEIVE_TIMEOUT`` bounds the *whole* ``sendall`` (CPython
# carries one deadline across the loop), so a client too slow to drain it is
# dropped with ABNORMAL_CLOSURE having received nothing at all -- an incomplete
# frame is never surfaced to the page -- and reconnects onto the identical
# backlog. Measured before this bound existed: 20 000 notifications (5.7 MB)
# against a client throttled to 150 KB/s failed three times out of three, each
# attempt identical, with no path to convergence and nothing logged.
#
# Both bounds are needed. The count bounds the query and the Python-side result
# set; the byte budget bounds the frame regardless of how large the individual
# messages are, which is what the send deadline actually cares about. 256 KiB is
# ~1.7s on a 150 KB/s link, an order of magnitude inside that deadline.
#
# Nothing is dropped: what does not fit stays in ``bus_bus`` and
# ``Websocket._dispatch_bus_notifications`` re-arms itself, continuing from its
# own watermark on the next pass.
MAX_NOTIFICATIONS_PER_POLL = 500
MAX_NOTIFICATION_BYTES_PER_POLL = 256 * 1024


_notify_conn: psycopg.Connection | None = None
_notify_lock = threading.Lock()
# Notify connections inherited from a parent process across fork() are parked
# here forever so they are never garbage collected in the child (see
# _reset_notify_state_in_child).
_notify_conns_inherited_from_parent = []


def _reset_notify_state_in_child():
    """Reset the notify-connection module state in a forked child process.

    The prefork master may have opened ``_notify_conn`` during preload (any
    ``_sendone`` postcommit); forked workers then inherit the same libpq
    socket, and using or closing it from one process corrupts the protocol
    stream / kills the shared backend for all the others.

    The inherited connection must therefore be *dropped without closing it*:
    ``close()`` would send a libpq Terminate message on the shared socket,
    terminating the backend the parent is still using.  Merely dropping the
    reference is safe at the libpq level — psycopg's ``PGconn.__del__`` has a
    pid guard (``self._procpid``) that skips ``PQfinish`` when the object is
    collected in a process other than the one that created it — but we
    additionally park the object in ``_notify_conns_inherited_from_parent``
    so it is never collected at all: this silences the ResourceWarning from
    ``Connection.__del__`` and stays safe even if psycopg's GC behavior
    changes.  The cost is one leaked fd per fork, and workers fork once.

    ``_notify_lock`` is recreated as well: another thread of the parent may
    have held it at fork time, in which case the child would inherit it
    locked forever.
    """
    global _notify_conn, _notify_lock  # noqa: PLW0603
    if _notify_conn is not None:
        _notify_conns_inherited_from_parent.append(_notify_conn)
        _notify_conn = None
    _notify_lock = threading.Lock()


# Registered once at module import (modules are only imported once per
# process, and forked children inherit the parent's registration).
os.register_at_fork(after_in_child=_reset_notify_state_in_child)


def _get_notify_conn_locked():
    """Return a persistent autocommit connection to the ``postgres`` database.

    Lazily opened on first call, reused thereafter.  Reconnects
    transparently if the connection was lost.

    Must only be called when the caller already holds ``_notify_lock``.
    """
    global _notify_conn  # noqa: PLW0603
    if _notify_conn is None or _notify_conn.closed:
        _dbname, params = odoo.db.connection_info_for("postgres")
        _notify_conn = psycopg.connect(autocommit=True, **params)
    return _notify_conn


def _close_notify_conn_locked():
    """Close the notify connection without acquiring ``_notify_lock``.

    Must only be called when the caller already holds ``_notify_lock``.
    """
    global _notify_conn  # noqa: PLW0603
    if _notify_conn is not None:
        with contextlib.suppress(psycopg.Error, OSError):
            _notify_conn.close()
        _notify_conn = None


def _close_notify_conn():
    """Close the persistent notify connection, if open.

    Acquires ``_notify_lock`` to prevent closing the connection under a
    concurrent ``_send_pg_notify`` call (e.g. at server shutdown).
    Do NOT call this while already holding ``_notify_lock``; use
    ``_close_notify_conn_locked()`` instead.
    """
    with _notify_lock:
        _close_notify_conn_locked()


def _send_pg_notify(payloads):
    """Send pg_notify on the ``postgres`` database.

    PostgreSQL LISTEN/NOTIFY is database-scoped: the bus loop
    (``ImDispatch.loop``) listens on the ``postgres`` database, so
    NOTIFY must also be sent on ``postgres``.

    Uses a persistent direct connection with ``autocommit=True`` (not
    the pool) so NOTIFY is sent immediately regardless of the caller's
    transaction state and without pool contention.

    Error handling distinguishes two failure classes:

    - *connection-level* errors (``OperationalError``/``InterfaceError``, or
      any error that left the connection closed): the connection is cycled
      and delivery is retried once on a fresh connection.  A second
      connection-level failure (or a failed reconnect) propagates to the
      caller; the undelivered wake-ups are lost, but the notifications
      themselves are committed in ``bus_bus`` and will be picked up on the
      next NOTIFY or dispatcher catch-up.
    - *per-payload* errors (e.g. a payload PostgreSQL rejects): logged as a
      warning and skipped, so one poison payload cannot drop the remaining
      payloads of the batch.

    Because the connection is in autocommit mode, each ``execute`` delivers its
    NOTIFY immediately, so already-sent payloads are not replayed on retry: the
    retry resumes at the payload that failed. (A payload that failed *after*
    committing may be sent twice, but imbus payloads are idempotent channel
    triggers deduplicated downstream by notification id.)
    """
    _query = psycopg.sql.SQL("SELECT {}('imbus', %s)").format(
        psycopg.sql.Identifier(ODOO_NOTIFY_FUNCTION)
    )
    payloads = list(payloads)
    sent = 0
    with _notify_lock:
        for attempt in range(2):
            try:
                # Inside the ``try``: a failure to *open* the connection is a
                # connection-level failure like any other and must go through the
                # same cycle-and-retry. Acquiring it outside meant the very first
                # connect -- the one case where a stale cached handle is most
                # likely -- propagated without the retry this loop exists for.
                conn = _get_notify_conn_locked()
                while sent < len(payloads):
                    try:
                        conn.execute(_query, (payloads[sent],))
                    except InterfaceError, psycopg.OperationalError:
                        raise
                    except Exception:
                        if conn.closed:
                            # The failure took the connection down: treat it
                            # as connection-level so this payload is retried
                            # on a fresh connection.
                            raise
                        # Poison payload: the connection is fine (autocommit:
                        # no aborted transaction to roll back), so skip it
                        # and keep sending the remaining payloads.
                        _logger.warning(
                            "Skipping imbus NOTIFY payload rejected by "
                            "PostgreSQL: %.200s",
                            payloads[sent],
                            exc_info=True,
                        )
                    sent += 1
                return
            except Exception:
                _close_notify_conn_locked()
                if attempt == 1:
                    raise


# ---------------------------------------------------------
# Bus
# ---------------------------------------------------------
def json_dump(v):
    """Serialize ``v`` to a JSON string using the shared orjson default encoder."""
    return json_dumps(v, default=orjson_default)


def hashable(key):
    """Convert ``key`` to a hashable form suitable for use in a dict/set.

    Lists are recursively converted to tuples: channels arrive as (possibly
    nested) JSON arrays on both the NOTIFY-payload side (``ImDispatch.loop``)
    and the websocket subscribe side, and both must produce identical keys.
    All other types are returned unchanged; callers must ensure the value is
    actually hashable after conversion.
    """
    if isinstance(key, list):
        return tuple(hashable(item) for item in key)
    return key


def channel_with_db(dbname, channel):
    """Qualify a raw channel with the database name to produce a scoped channel key.

    Accepted forms and their output:
    - ``Model`` instance           → ``(dbname, model_name, record_id)``
    - ``(Model, subchannel)``      → ``(dbname, model_name, record_id, subchannel)``
    - ``str``                      → ``(dbname, channel_str)``
    - anything else (e.g. tuple)   → passed through unchanged (pre-qualified)
    """
    if isinstance(channel, models.Model):
        return (dbname, channel._name, channel.id)
    if (
        isinstance(channel, tuple)
        and len(channel) == 2
        and isinstance(channel[0], models.Model)
    ):
        return (dbname, channel[0]._name, channel[0].id, channel[1])
    if isinstance(channel, str):
        return (dbname, channel)
    return channel


def get_notify_payloads(channels):
    """Serialize ``channels`` into JSON-array payloads for the imbus NOTIFY.

    Each channel is serialized exactly once, then the serialized channels are
    greedily packed (in order, linear time) into as few payloads as possible
    while keeping every payload's encoded size strictly under
    ``NOTIFY_PAYLOAD_MAX_LENGTH`` (PostgreSQL rejects larger NOTIFY payloads).

    A single channel whose payload cannot fit under the limit on its own is
    dropped with a warning: emitting it would produce a NOTIFY that is
    guaranteed to fail, and it can never succeed no matter how it is split.

    :param list channels:
    :return: list of JSON-array payloads
    :rtype: list[str]
    """
    payloads = []
    items = []  # serialized channels of the payload being built
    items_len = 0  # sum of the encoded lengths of ``items``
    for channel in channels:
        item = json_dump(channel)
        item_len = len(item.encode())
        # A payload of n items encodes to: "[" + items + n-1 "," + "]",
        # i.e. items_len + len(items) + 1 bytes.
        if item_len + 2 >= NOTIFY_PAYLOAD_MAX_LENGTH:
            # Error, not warning: nothing recovers from this. The channel's
            # subscribers are simply never woken for these notifications, and
            # only an unrelated later NOTIFY (or a dispatcher catch-up) brings
            # them back -- a silent delivery loss deserves an error-level trace.
            _logger.error(
                "Dropping imbus channel whose %d-byte NOTIFY payload exceeds "
                "the %d-byte limit: %.200s",
                item_len + 2,
                NOTIFY_PAYLOAD_MAX_LENGTH,
                item,
            )
            continue
        if items and items_len + len(items) + item_len + 2 >= NOTIFY_PAYLOAD_MAX_LENGTH:
            payloads.append(f"[{','.join(items)}]")
            items = []
            items_len = 0
        items.append(item)
        items_len += item_len
    if items:
        payloads.append(f"[{','.join(items)}]")
    return payloads


class BusBus(models.Model):
    _name = "bus.bus"

    _description = "Communication Bus"

    channel = fields.Char("Channel")
    message = fields.Char("Message")

    _channel_id_idx = models.Index("(channel, id)")
    _create_date_idx = models.Index("(create_date)")

    @api.autovacuum
    def _gc_messages(self):
        """Delete bus messages older than the configured retention window.

        Falls back to ``DEFAULT_GC_RETENTION_SECONDS`` (with a warning) if the
        parameter is absent, non-numeric, or non-positive (a zero or negative
        value would wipe the entire table by making timeout_ago >= now).
        """
        param_value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("bus.gc_retention_seconds", DEFAULT_GC_RETENTION_SECONDS)
        )
        try:
            gc_retention_seconds = int(param_value)
        except ValueError, TypeError:
            _logger.warning(
                "bus.gc_retention_seconds is %r (must be an integer); using default %d seconds.",
                param_value,
                DEFAULT_GC_RETENTION_SECONDS,
            )
            gc_retention_seconds = DEFAULT_GC_RETENTION_SECONDS
        if gc_retention_seconds <= 0:
            _logger.warning(
                "bus.gc_retention_seconds is %d (must be > 0); using default %d seconds.",
                gc_retention_seconds,
                DEFAULT_GC_RETENTION_SECONDS,
            )
            gc_retention_seconds = DEFAULT_GC_RETENTION_SECONDS
        timeout_ago = fields.Datetime.now() - datetime.timedelta(
            seconds=gc_retention_seconds
        )
        # Direct SQL to avoid ORM overhead; this way we can delete millions of rows quickly.
        # This is a low-level table with no expected references, and doing this avoids
        # the need to split or reschedule this GC job.
        self.env.cr.execute(
            "DELETE FROM bus_bus WHERE create_date < %s", (timeout_ago,)
        )

    @api.model
    def _sendone(self, target, notification_type, message):
        """Low-level method to send ``notification_type`` and ``message`` to ``target``.

        Using ``_bus_send()`` from ``mixin.bus.listener`` is recommended for simplicity and
        security.

        When using ``_sendone`` directly, ``target`` (if str) should not be guessable by an
        attacker.
        """
        self._ensure_hooks()
        channel = channel_with_db(self.env.cr.dbname, target)
        self.env.cr.precommit.data["bus.bus.values"].append(
            {
                "channel": json_dump(channel),
                "message": json_dump(
                    {
                        "type": notification_type,
                        "payload": message,
                    }
                ),
            }
        )
        self.env.cr.postcommit.data["bus.bus.channels"].add(channel)

    def _ensure_hooks(self):
        if "bus.bus.values" not in self.env.cr.precommit.data:
            self.env.cr.precommit.data["bus.bus.values"] = []

            @self.env.cr.precommit.add
            def create_bus():
                self.sudo().create(self.env.cr.precommit.data.pop("bus.bus.values"))

        if "bus.bus.channels" not in self.env.cr.postcommit.data:
            self.env.cr.postcommit.data["bus.bus.channels"] = OrderedSet()
            # Stamped here, at the transaction's FIRST _sendone, and read by
            # the postcommit hook below. It has to live in ``postcommit.data``:
            # ``precommit.data`` is cleared by ``Callbacks.run()`` when the
            # precommit hooks fire, which happens before postcommit runs -- so
            # a stamp kept there is always gone by the time it is needed.
            self.env.cr.postcommit.data["bus.bus.first_sendone"] = time.monotonic()

            # We have to wait until the notifications are commited in database.
            # When calling `NOTIFY imbus`, notifications will be fetched in the
            # bus table. If the transaction is not commited yet, there will be
            # nothing to fetch, and the websocket will return no notification.
            cr_ref = self.env.cr

            @cr_ref.postcommit.add
            def notify():
                channels = list(cr_ref.postcommit.data.pop("bus.bus.channels"))
                # ids are assigned at INSERT but delivery happens at COMMIT, so
                # a notification created long before its commit can be skipped
                # once the receiving websocket's hold-back window has moved
                # past its id -- silently, and only for clients that received
                # something else in the meantime, which makes it close to
                # undiagnosable in production. Measured on this build: a
                # notification held ~15s was still delivered, one held ~25s was
                # lost. Warn from the window onwards, naming the channels, so
                # the offending long transaction can actually be found.
                held_for = time.monotonic() - cr_ref.postcommit.data.pop(
                    "bus.bus.first_sendone", time.monotonic()
                )
                if held_for > NOTIFICATION_HOLD_BACK_SECONDS:
                    _logger.warning(
                        "Bus notification created %.1fs before its commit, "
                        "beyond the %ds hold-back window: it may never be "
                        "dispatched to clients that received other "
                        "notifications meanwhile. Create bus notifications as "
                        "close to the commit as possible. Channels: %.300s",
                        held_for,
                        NOTIFICATION_HOLD_BACK_SECONDS,
                        channels,
                    )
                payloads = get_notify_payloads(channels)
                if len(payloads) > 1:
                    _logger.info(
                        "The imbus notification payload was too large, it's been split into %d payloads.",
                        len(payloads),
                    )
                try:
                    _send_pg_notify(payloads)
                except Exception:
                    # A postcommit hook must never raise: the transaction is
                    # already committed, and Callbacks.run() has no per-callback
                    # error handling, so raising would skip every remaining
                    # postcommit hook (mail sending, attachment GC, ...) and
                    # fail a request whose work is already committed.  The
                    # notifications themselves are safely committed in bus_bus;
                    # only the NOTIFY wake-up is lost, and websockets recover on
                    # the next NOTIFY or dispatcher catch-up.
                    _logger.exception(
                        "Failed to send imbus NOTIFY; delivery of the committed "
                        "bus notifications will be delayed."
                    )

    @api.model
    def _poll(
        self, channels, last=0, ignore_ids=None, limit=MAX_NOTIFICATIONS_PER_POLL
    ):
        """Return the notifications of ``channels`` newer than ``last``.

        Bounded: at most ``limit`` notifications, and at most
        ``MAX_NOTIFICATION_BYTES_PER_POLL`` bytes of message payload. Callers
        that must drain a backlog should use :meth:`_poll_batch`, which reports
        whether more is waiting.
        """
        return self._poll_batch(channels, last, ignore_ids, limit)[0]

    @api.model
    def _poll_batch(
        self,
        channels,
        last=0,
        ignore_ids=None,
        limit=MAX_NOTIFICATIONS_PER_POLL,
        max_bytes=MAX_NOTIFICATION_BYTES_PER_POLL,
    ):
        """Poll one bounded batch of notifications.

        :return: ``(notifications, truncated)`` where ``truncated`` says that at
            least one further notification matched but did not fit in this batch,
            so the caller should poll again once this one is delivered. See
            ``MAX_NOTIFICATIONS_PER_POLL`` for why the bounds exist at all.
        """
        # Direct SQL — bus.bus is a simple queue table with no computed fields.
        # Channel filtering provides security; sudo/access rules are unnecessary.
        if last == 0:
            timeout_ago = fields.Datetime.now() - datetime.timedelta(
                seconds=POLL_LOOKBACK_SECONDS
            )
            where = SQL("create_date > %s", timeout_ago)
        else:
            where = SQL("id > %s", last)
        if ignore_ids:
            where = SQL("%s AND NOT (id = ANY(%s))", where, ignore_ids)
        channels = [json_dump(channel_with_db(self.env.cr.dbname, c)) for c in channels]
        # One row beyond the limit, so "there is more" is answered by the query
        # itself rather than by a second round trip.
        self.env.cr.execute(
            SQL(
                "SELECT id, message FROM bus_bus WHERE %s AND channel = ANY(%s)"
                " ORDER BY id LIMIT %s",
                where,
                channels,
                limit + 1,
            )
        )
        rows = self.env.cr.fetchall()
        truncated = len(rows) > limit
        del rows[limit:]
        notifications = []
        payload_bytes = 0
        for row in rows:
            # Measured on the stored JSON, before parsing: this is what the
            # outgoing frame will actually carry, and it costs nothing to read.
            payload_bytes += len(row[1])
            notifications.append({"id": row[0], "message": json_loads(row[1])})
            if payload_bytes >= max_bytes:
                truncated = truncated or len(notifications) < len(rows)
                break
        return notifications, truncated

    def _bus_last_id(self):
        self.env.cr.execute("SELECT COALESCE(MAX(id), 0) FROM bus_bus")
        return self.env.cr.fetchone()[0]


# ---------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------


def _keep_session_alive_while_idle(conn):
    """Opt ``conn`` out of PostgreSQL's ``idle_session_timeout``.

    The dispatcher connection exists in order to sit idle: between two
    NOTIFYs it issues no statement at all, which is precisely the shape that
    ``idle_session_timeout`` reaps.  On a server that sets it, the LISTEN is
    therefore torn down once per window no matter how healthy everything is,
    and the reconnect is not free: ``loop`` cannot know which NOTIFYs were
    lost while it was down, so it falls back on ``_dispatch_to_all`` and
    wakes *every* subscribed websocket.

    The opt-out belongs on this session rather than on the server or the
    role: that timeout is there to reap genuinely leaked connections, and a
    deliberately idle listener is the one connection that must be exempt
    from it. `service/_cron.arm_cron_listen` already does this for the cron
    channel; this was the remaining LISTEN in the tree without it.

    Best effort by design.  The parameter only exists from PostgreSQL 14, and
    a transaction-pooling connection pooler discards the ``SET`` when it
    hands the backend on -- but such a pooler breaks ``LISTEN`` outright, so
    there is nothing further to lose.  Either way the loop still works; it
    just goes back to reconnecting on a timer.
    """
    try:
        conn.execute("SET idle_session_timeout = 0")
    except psycopg.Error as exc:
        _logger.info(
            "Bus.loop could not clear idle_session_timeout, the LISTEN "
            "connection may be reaped while idle: %s",
            exc,
        )


class ImDispatch(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name=f"{__name__}.Bus")
        self._channels_to_ws = {}
        # Serialises all mutations to _channels_to_ws and the loop's
        # snapshot read, preventing races between the dispatch loop and
        # concurrent subscribe/unsubscribe calls from websocket threads.
        self._lock = threading.Lock()
        # True until the first LISTEN of this process is established; used to
        # skip the pointless (and wake-up-storm-prone) catch-up dispatch on
        # process start, when no notification can have been missed yet.
        self._first_listen = True
        # Whether ``start()`` was ever called on this singleton. The thread is
        # started lazily (first ``subscribe()``), so ``is_alive()`` alone
        # cannot distinguish "not needed yet" from "died" -- see ``is_healthy``.
        # NOT ``_started``: ``threading.Thread`` already owns that name (an
        # ``Event`` backing ``is_alive()``); shadowing it breaks the thread.
        self._ever_started = False

    @property
    def is_healthy(self):
        """Whether the dispatcher is in a state that can deliver notifications.

        A process that has never served a websocket has never started the
        thread, and is perfectly healthy: reporting on ``is_alive()`` alone
        would fail every freshly booted server until its first subscriber.
        Only a dispatcher that was started and has since died -- or a server
        on its way down -- is unhealthy.
        """
        return not stop_event.is_set() and (not self._ever_started or self.is_alive())

    def _ensure_started(self):
        """Start the dispatch thread if it is not running yet (idempotent)."""
        # RuntimeError: another thread won the race and started it already, or
        # the thread already ran and terminated (which ``is_healthy`` reports).
        with contextlib.suppress(RuntimeError):
            if not self.is_alive():
                self.start()
        self._ever_started = True

    def subscribe(self, channels, last, db, websocket):
        """Subscribe to bus notifications.

        Every notification related to the given channels will be sent through
        the websocket. Replaces any existing subscription for this websocket.
        """
        channels = {hashable(channel_with_db(db, c)) for c in channels}
        outdated_channels = websocket._channels - channels
        with self._lock:
            for channel in channels:
                self._channels_to_ws.setdefault(channel, set()).add(websocket)
            for channel in outdated_channels:
                ws_set = self._channels_to_ws.get(channel)
                if ws_set is not None:
                    ws_set.discard(websocket)
                    if not ws_set:
                        del self._channels_to_ws[channel]
        websocket.subscribe(channels, last)
        self._ensure_started()

    def unsubscribe(self, websocket):
        """Remove a websocket from all channel subscriptions."""
        with self._lock:
            for channel in websocket._channels:
                ws_set = self._channels_to_ws.get(channel)
                if ws_set is not None:
                    ws_set.discard(websocket)
                    if not ws_set:
                        del self._channels_to_ws[channel]

    def loop(self):
        """Dispatch postgres notifications to the relevant websockets.

        Uses a direct connection (not the pool) so the long-lived LISTEN
        connection does not consume a pool slot.
        """
        _logger.info("Bus.loop listen imbus on db postgres")
        _dbname, params = odoo.db.connection_info_for("postgres")
        with (
            psycopg.connect(autocommit=True, **params) as conn,
            selectors.DefaultSelector() as sel,
        ):
            _keep_session_alive_while_idle(conn)
            conn.execute("LISTEN imbus")
            sel.register(conn, selectors.EVENT_READ)
            if self._first_listen:
                # First LISTEN of this process: there is no gap to catch up
                # on, and each websocket already polls when it subscribes.
                self._first_listen = False
            else:
                # NOTIFYs emitted while the LISTEN connection was down were
                # lost: without a catch-up, a notification created during the
                # gap is never dispatched until its channel receives another
                # one. Websockets track their own ``last_id``, so waking them
                # all is a cheap incremental poll.
                self._dispatch_to_all()
            while not stop_event.is_set():
                if sel.select(DISPATCHER_SELECT_TIMEOUT):
                    channels = []
                    for notif in conn.notifies(timeout=0):
                        channels.extend(self._parse_imbus_payload(notif.payload))
                    for websocket in self._collect_websockets(channels):
                        websocket.trigger_notification_dispatching()

    @staticmethod
    def _parse_imbus_payload(payload):
        """Parse one imbus NOTIFY payload into a list of channels.

        A malformed payload (foreign NOTIFY on the imbus channel, custom
        ``ODOO_NOTIFY_FUNCTION``, ...) must not kill the dispatch loop for
        every database: it is logged and skipped instead.
        """
        try:
            channels = json_loads(payload)
        except ValueError:
            _logger.warning("Bus.loop ignoring malformed imbus payload: %r", payload)
            return []
        if not isinstance(channels, list):
            _logger.warning("Bus.loop ignoring non-list imbus payload: %r", payload)
            return []
        return channels

    def _collect_websockets(self, channels):
        """Snapshot the websockets subscribed to any of ``channels``.

        The snapshot is taken under lock, so the caller can dispatch outside
        the lock without racing subscribe/unsubscribe.  A channel that cannot
        be converted to a hashable key (e.g. it contains a JSON object) is
        logged and skipped: a single bad NOTIFY payload must not kill the
        dispatch loop (defense in depth on top of ``_parse_imbus_payload``).
        """
        websockets = set()
        with self._lock:
            for channel in channels:
                try:
                    websockets.update(self._channels_to_ws.get(hashable(channel), ()))
                except TypeError:
                    _logger.warning("Bus.loop ignoring unhashable channel: %r", channel)
        return websockets

    def _dispatch_to_all(self):
        """Trigger notification dispatching on every subscribed websocket.

        Used to catch up after the LISTEN connection was re-established.
        Websockets are woken in chunks of ``DISPATCH_CATCHUP_CHUNK_SIZE`` with
        a ``DISPATCH_CATCHUP_CHUNK_DELAY`` pause in between: waking thousands
        of websockets at once right after a database hiccup exhausts the
        cursor pool (mass TRY_LATER disconnects, then a reconnect storm at the
        worst possible moment).  Pausing loses nothing: notifications stay in
        ``bus_bus`` and each websocket polls from its own ``last_id`` once
        woken, while new NOTIFYs accumulate on the already-established LISTEN
        connection and are processed right after this catch-up.
        """
        with self._lock:
            websockets = set().union(*self._channels_to_ws.values())
        for count, websocket in enumerate(websockets):
            if count and count % DISPATCH_CATCHUP_CHUNK_SIZE == 0:
                if stop_event.wait(DISPATCH_CATCHUP_CHUNK_DELAY):
                    return  # server is shutting down
            websocket.trigger_notification_dispatching()

    def run(self):
        # Exponential backoff between retries: a transient hiccup recovers
        # within seconds (the previous flat 50s pause left every websocket
        # without dispatching for almost a minute), while a persistent outage
        # (PostgreSQL down) quickly settles at one retry per
        # MAX_DISPATCHER_RETRY_DELAY to keep
        # log noise bounded.
        retry_delay = 1
        while not stop_event.is_set():
            started_at = time.monotonic()
            try:
                self.loop()
            except Exception as exc:
                if (
                    isinstance(exc, (InterfaceError, psycopg.OperationalError))
                    and stop_event.is_set()
                ):
                    continue
                if time.monotonic() - started_at > MAX_DISPATCHER_RETRY_DELAY:
                    # The loop ran fine for a while before failing: this is a
                    # new incident, not a consecutive failure. Restart the
                    # backoff from scratch.
                    retry_delay = 1
                _logger.exception("Bus.loop error, retry in %d seconds", retry_delay)
                # `wait` (vs `sleep`) aborts the pause on server shutdown.
                stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_DISPATCHER_RETRY_DELAY)


# Lazy-started singleton — initialized early to avoid "Bus unavailable" errors.
# ImDispatch.start() is deferred until the first subscribe() call.
dispatch = ImDispatch()
stop_event = threading.Event()
CommonServer.on_stop(stop_event.set)
CommonServer.on_stop(_close_notify_conn)
