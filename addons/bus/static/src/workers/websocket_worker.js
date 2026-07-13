/** @odoo-module native */
import { debounce, Deferred, Logger } from "./bus_worker_utils.js";
import {
    CONNECTION_STATE,
    WEBSOCKET_CLOSE_CODES,
    WEBSOCKET_READY_STATE,
} from "./websocket_worker_constants.js";

/**
 * @deprecated Import from `./websocket_worker_constants.js` instead: that
 * module exists precisely so page code never has to import this (worker-
 * oriented, side-effectful) module for a constant. Kept only for legacy
 * importers that cannot be edited from the bus module (`web` user-switch tour,
 * `auth_totp` tour, `mail` bus_connection_alert test) and for bus test files
 * (to be migrated). `WORKER_STATE` is itself a deprecated alias of
 * `CONNECTION_STATE`.
 */
export { WEBSOCKET_CLOSE_CODES, WORKER_STATE } from "./websocket_worker_constants.js";

/**
 * Type of events that can be sent from the worker to its clients.
 *
 * @typedef { 'BUS:CONNECT' | 'BUS:RECONNECT' | 'BUS:DISCONNECT' | 'BUS:RECONNECTING' | 'BUS:NOTIFICATION' | 'BUS:INITIALIZED' | 'BUS:OUTDATED'| 'BUS:WORKER_STATE_UPDATED' | 'BUS:PROVIDE_LOGS' | 'BUS:PING' } WorkerEvent
 */

/**
 * Type of action that can be sent from the client to the worker.
 *
 * @typedef {'BUS:ADD_CHANNEL' | 'BUS:DELETE_CHANNEL' | 'BUS:SET_CHANNELS' | 'BUS:FORCE_UPDATE_CHANNELS' | 'BUS:INITIALIZE_CONNECTION' | 'BUS:REQUEST_LOGS' | 'BUS:SEND' | 'BUS:SET_LOGGING_ENABLED' | 'BUS:LEAVE' | 'BUS:STOP' | 'BUS:START' | 'BUS:PONG'} WorkerAction
 */

const MAXIMUM_RECONNECT_DELAY = 60000;
const UUID = Date.now().toString(36) + Math.random().toString(36).substring(2);
const logger = new Logger("bus_websocket_worker");

/**
 * This class regroups the logic necessary in order for the
 * SharedWorker/Worker to work. Indeed, Safari and some minor browsers
 * do not support SharedWorker. In order to solve this issue, a Worker
 * is used in this case. The logic is almost the same than the one used
 * for SharedWorker and this class implements it.
 */
export class WebsocketWorker {
    INITIAL_RECONNECT_DELAY = 1000;
    RECONNECT_JITTER = 1000;
    CONNECTION_CHECK_DELAY = 60_000;
    // How often dead clients are looked for, and how long a client may stay
    // silent before it is pinged (half the timeout) then evicted (full
    // timeout). Deliberately generous: a bfcache-frozen tab cannot answer
    // pings, and while `bus_service` replays its channels on `pageshow`, an
    // aggressive timeout would churn subscriptions for nothing.
    CLIENT_LIVENESS_SWEEP_DELAY = 120_000;
    CLIENT_LIVENESS_TIMEOUT = 600_000;
    // How long a dispatched notification id is remembered for deduplication.
    // Mirrors the server's hold-back window (`Websocket.
    // MAX_NOTIFICATION_HISTORY_SEC = 10` in bus/websocket.py): the server
    // deliberately re-delivers ids it cannot yet prove were received exactly
    // once, and holds `last_id` back for that many seconds so notifications
    // committed out of id order by concurrent transactions are not skipped.
    // Anything older than the window can no longer be legitimately re-sent,
    // so remembering it here would be pure memory overhead. Kept a bit larger
    // than the server's to absorb clock/scheduling slack.
    SEEN_NOTIFICATION_RETENTION_MS = 15_000;
    // Defensive cap: a pathological notification flood must not grow the
    // seen-id map without bound between prunes.
    SEEN_NOTIFICATION_MAX_COUNT = 10_000;

    constructor(name) {
        this.name = name;
        // Timestamp of start of most recent bus service sender
        this.newestStartTs = undefined;
        this.websocketURL = "";
        this.currentUID = null;
        this.currentDB = null;
        this.isWaitingForNewUID = true;
        this.channelsByClient = new Map();
        // Last time each client was heard from — feeds the liveness sweep: a
        // tab that crashed or was OOM-killed never sends BUS:LEAVE, and its
        // port would otherwise stay in `channelsByClient` forever, keeping
        // the server subscribed to channels no live tab wants and receiving
        // every broadcast.
        this.lastSeenByClient = new Map();
        this._startClientLivenessSweep();
        this.connectRetryDelay = this.INITIAL_RECONNECT_DELAY;
        this.connectTimeout = null;
        this.debugModeByClient = new Map();
        this.isDebug = false;
        this.active = true;
        this.state = CONNECTION_STATE.IDLE;
        this.isReconnecting = false;
        this.lastChannelSubscription = null;
        this.loggingEnabled = null;
        this.firstSubscribeDeferred = new Deferred();
        // Highest notification id seen so far. NOT used for deduplication
        // (see `seenNotificationIds`): only sent as `last` on subscribe.
        this.lastNotificationId = 0;
        // Recently dispatched notification ids (id -> seen timestamp), kept
        // for `SEEN_NOTIFICATION_RETENTION_MS`. This is the dedup source of
        // truth: the server may legitimately deliver LOWER ids in LATER
        // batches (its hold-back window for out-of-order commits), so a
        // monotonic watermark filter would silently drop them.
        this.seenNotificationIds = new Map();
        this.messageWaitQueue = [];
        this._forceUpdateChannels = debounce(this._forceUpdateChannels, 300);
        this._debouncedUpdateChannels = debounce(this._updateChannels, 300);
        this._debouncedSendToServer = debounce(this._sendToServer, 300);

        this._onWebsocketClose = this._onWebsocketClose.bind(this);
        this._onWebsocketError = this._onWebsocketError.bind(this);
        this._onWebsocketMessage = this._onWebsocketMessage.bind(this);
        this._onWebsocketOpen = this._onWebsocketOpen.bind(this);

        globalThis.addEventListener("error", ({ error }) => {
            const params =
                error instanceof Error
                    ? [error.constructor.name, error.stack]
                    : [error];
            this._logDebug("Unhandled error", ...params);
        });
        globalThis.addEventListener("unhandledrejection", ({ reason }) => {
            const params =
                reason instanceof Error
                    ? [reason.constructor.name, reason.stack]
                    : [reason];
            this._logDebug("Unhandled rejection", params);
        });
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /**
     * Send the message to all the clients that are connected to the
     * worker.
     *
     * @param {WorkerEvent} type Event to broadcast to connected
     * clients.
     * @param {Object} data
     */
    broadcast(type, data) {
        this._logDebug("broadcast", type, data);
        // No JSON round-trip needed: everything broadcast here is already
        // plain, structured-cloneable data — notification batches come
        // straight out of `JSON.parse` in `_onWebsocketMessage`, the rest are
        // literals built in this file — and `postMessage` structured-clones
        // per client anyway, so the receiving pages never share state with
        // the worker (or with each other).
        for (const client of this.channelsByClient.keys()) {
            client.postMessage({ type, data: data ?? undefined });
        }
    }

    /**
     * Register a client handled by this worker.
     *
     * @param {MessagePort} messagePort
     */
    registerClient(messagePort) {
        messagePort.addEventListener("message", (ev) => {
            this._onClientMessage(messagePort, ev.data);
        });
        this.channelsByClient.set(messagePort, new Map());
        this.lastSeenByClient.set(messagePort, Date.now());
    }

    /**
     * Send message to the given client.
     *
     * @param {MessagePort} client
     * @param {WorkerEvent} type
     * @param {Object} data
     */
    sendToClient(client, type, data) {
        if (type !== "BUS:PROVIDE_LOGS") {
            this._logDebug("sendToClient", type, data);
        }
        // Same provenance guarantee as `broadcast`: data is either parsed
        // JSON or literals built here, and `postMessage` structured-clones —
        // a defensive JSON round-trip would be pure overhead.
        client.postMessage({ type, data: data ?? undefined });
    }

    //--------------------------------------------------------------------------
    // PRIVATE
    //--------------------------------------------------------------------------

    /**
     * Called when a message is posted to the worker by a client (i.e. a
     * MessagePort connected to this worker).
     *
     * @param {MessagePort} client
     * @param {Object} message
     * @param {WorkerAction} [message.action]
     * Action to execute.
     * @param {Object|undefined} [message.data] Data required by the
     * action.
     */
    _onClientMessage(client, { action, data }) {
        this._logDebug("_onClientMessage", action, data);
        // Any message proves the port's page is alive and unfrozen.
        this.lastSeenByClient.set(client, Date.now());
        if (
            !this.channelsByClient.has(client) &&
            action?.startsWith("BUS:") &&
            action !== "BUS:LEAVE" &&
            action !== "BUS:PONG"
        ) {
            // (BUS:PONG is also excluded above: it proves liveness but does
            // not re-register — a pong racing an eviction would otherwise
            // resurrect the client with an EMPTY channel list while its tab
            // still believes it is subscribed.)
            // A client that previously sent BUS:LEAVE (`bus_service.stop()`,
            // bfcache pagehide) was dropped from `channelsByClient` and no
            // longer receives broadcasts. It messaging us again with a BUS
            // action proves it participates in the bus again: re-register it,
            // otherwise a `stop()`/`start()` cycle leaves the tab permanently
            // deaf and a subsequent BUS:ADD_CHANNEL crashes on the missing
            // channel list. The BUS: prefix check matters: this handler sees
            // EVERY message on the shared port, including ELECTION:*/BASE:*
            // traffic, and the election heartbeat (sent every 1.5s by the
            // main tab) must not silently resurrect a stopped client.
            this.channelsByClient.set(client, new Map());
        }
        switch (action) {
            case "BUS:SEND": {
                if (data["event_name"] === "update_presence") {
                    this._debouncedSendToServer(data);
                } else {
                    this._sendToServer(data);
                }
                return;
            }
            case "BUS:START":
                return this._start();
            case "BUS:STOP":
                return this._stop();
            case "BUS:LEAVE":
                return this._unregisterClient(client);
            case "BUS:ADD_CHANNEL":
                return this._addChannel(client, data);
            case "BUS:DELETE_CHANNEL":
                return this._deleteChannel(client, data);
            case "BUS:SET_CHANNELS":
                return this._setChannels(client, data);
            case "BUS:FORCE_UPDATE_CHANNELS":
                return this._forceUpdateChannels();
            case "BUS:SET_LOGGING_ENABLED":
                this.loggingEnabled = data;
                break;
            case "BUS:REQUEST_LOGS":
                logger
                    .getLogs()
                    // IndexedDB can be unavailable (private browsing, quota):
                    // still answer with the worker info instead of leaving an
                    // unhandled rejection and a download that never arrives.
                    .catch((error) => [`getLogs failed: ${error}`])
                    .then((logs) => {
                        const workerInfo = {
                            UUID,
                            active: this.active,
                            channels: this._getAllChannels(),
                            db: this.currentDB,
                            is_reconnecting: this.isReconnecting,
                            last_subscription: this.lastChannelSubscription,
                            name: this.name,
                            number_of_clients: this.channelsByClient.size,
                            reconnect_delay: this.connectRetryDelay,
                            uid: this.currentUID,
                            websocket_url: this.websocketURL,
                        };
                        this.sendToClient(client, "BUS:PROVIDE_LOGS", {
                            workerInfo,
                            logs,
                        });
                    });
                break;
            case "BUS:INITIALIZE_CONNECTION":
                return this._initializeConnection(client, data);
        }
    }

    /**
     * Add a channel for the given client. Channels are REFCOUNTED per
     * client: several independent features of one tab may claim the same
     * channel (e.g. two im_livechat features), and each of their deletes
     * must only release its own claim. If this channel is not yet known,
     * update the subscription on the server.
     *
     * @param {MessagePort} client
     * @param {string} channel
     */
    _addChannel(client, channel) {
        const clientChannels = this.channelsByClient.get(client);
        clientChannels.set(channel, (clientChannels.get(channel) ?? 0) + 1);
        this._debouncedUpdateChannels();
    }

    /**
     * Release one claim on a channel for the given client; the channel is
     * only removed when its refcount reaches 0. If this channel is not
     * used anymore, update the subscription on the server.
     *
     * @param {MessagePort} client
     * @param {string} channel
     */
    _deleteChannel(client, channel) {
        const clientChannels = this.channelsByClient.get(client);
        const count = clientChannels?.get(channel);
        if (!count) {
            return;
        }
        if (count === 1) {
            clientChannels.delete(channel);
        } else {
            clientChannels.set(channel, count - 1);
        }
        this._debouncedUpdateChannels();
    }

    /**
     * Atomically replace the given client's channel claims. Used by
     * `bus_service` to replay a tab's full channel map (bfcache restore
     * after a liveness eviction, `start()` after `stop()`): a snapshot is
     * immune to the drift an incremental add/delete replay could introduce.
     *
     * @param {MessagePort} client
     * @param {[string, number][]} entries channel -> refcount pairs
     */
    _setChannels(client, entries) {
        const clientChannels = new Map();
        for (const [channel, count] of entries ?? []) {
            if (count > 0) {
                clientChannels.set(channel, count);
            }
        }
        this.channelsByClient.set(client, clientChannels);
        this._debouncedUpdateChannels();
    }

    /**
     * Channels claimed (refcount > 0) by at least one client, sorted.
     *
     * @returns {string[]}
     */
    _getAllChannels() {
        const channels = new Set();
        for (const clientChannels of this.channelsByClient.values()) {
            for (const channel of clientChannels.keys()) {
                channels.add(channel);
            }
        }
        return [...channels].sort();
    }

    /**
     * Update the channels on the server side even if the channels on
     * the client side are the same than the last time we subscribed.
     */
    _forceUpdateChannels() {
        this._updateChannels({ force: true });
    }

    /**
     * Remove the given client from this worker client list as well as
     * its channels. If some of its channels are not used anymore,
     * update the subscription on the server.
     *
     * @param {MessagePort} client
     */
    _unregisterClient(client) {
        this.channelsByClient.delete(client);
        this.lastSeenByClient.delete(client);
        this.debugModeByClient.delete(client);
        this.isDebug = [...this.debugModeByClient.values()].some(Boolean);
        this._debouncedUpdateChannels();
    }

    /**
     * Periodically look for dead clients. A tab that crashed or was
     * OOM-killed never sends BUS:LEAVE; without a sweep its port stays
     * registered forever — its channels pad every server subscription and
     * every broadcast posts to a dead port.
     */
    _startClientLivenessSweep() {
        setInterval(
            () => this._sweepClientLiveness(),
            this.CLIENT_LIVENESS_SWEEP_DELAY,
        );
    }

    _sweepClientLiveness() {
        const now = Date.now();
        for (const [client, lastSeen] of this.lastSeenByClient) {
            const age = now - lastSeen;
            if (age > this.CLIENT_LIVENESS_TIMEOUT) {
                this._logDebug("liveness_evict", { age });
                this._unregisterClient(client);
                // Let composed handlers (the election worker) drop the port
                // too; see `onClientEvicted` wiring in bus_worker_script.js.
                this.onClientEvicted?.(client);
            } else if (age > this.CLIENT_LIVENESS_TIMEOUT / 2) {
                // Silent for a while: ask for a sign of life. Live tabs
                // answer BUS:PONG immediately; frozen (bfcache) or dead ones
                // cannot and reach the eviction branch on a later sweep.
                this.sendToClient(client, "BUS:PING");
            }
        }
    }

    /**
     * Initialize a client connection to this worker.
     *
     * @param {Object} param0
     * @param {string} [param0.db] Database name.
     * @param {String} [param0.debug] Current debugging mode for the
     * given client.
     * @param {Number} [param0.lastNotificationId] Last notification id
     * known by the client.
     * @param {String} [param0.websocketURL] URL of the websocket endpoint.
     * @param {Number|false|undefined} [param0.uid] Current user id
     *     - Number: user is logged whether on the frontend/backend.
     *     - false: user is not logged.
     *     - undefined: not available (e.g. livechat support page)
     * @param {Number} param0.startTs Timestamp of start of bus service sender.
     */
    _initializeConnection(
        client,
        { db, debug, lastNotificationId, uid, websocketURL, startTs },
    ) {
        if (this.newestStartTs && this.newestStartTs > startTs) {
            this.debugModeByClient.set(client, debug);
            this.isDebug = [...this.debugModeByClient.values()].some(Boolean);
            this.sendToClient(client, "BUS:WORKER_STATE_UPDATED", this.state);
            this.sendToClient(client, "BUS:INITIALIZED");
            return;
        }
        this.newestStartTs = startTs;
        this.websocketURL = websocketURL;
        // Never let a newly-attaching tab rewind the shared high-watermark:
        // its localStorage snapshot may lag behind notifications this worker
        // has already dispatched, which would make the server re-deliver them.
        this.lastNotificationId = Math.max(
            this.lastNotificationId ?? 0,
            lastNotificationId ?? 0,
        );
        this.debugModeByClient.set(client, debug);
        this.isDebug = [...this.debugModeByClient.values()].some(Boolean);
        const isCurrentUserKnown = uid !== undefined;
        if (this.isWaitingForNewUID && isCurrentUserKnown) {
            this.isWaitingForNewUID = false;
            this.currentUID = uid;
        }
        this.currentDB ||= db;
        if (
            (this.currentUID !== uid && isCurrentUserKnown) ||
            (db && this.currentDB !== db)
        ) {
            this.currentUID = uid;
            this.currentDB = db || this.currentDB;
            if (this.websocket) {
                this.websocket.close(WEBSOCKET_CLOSE_CODES.CLEAN);
            }
            this.channelsByClient.forEach((_, key) =>
                this.channelsByClient.set(key, new Map()),
            );
            // `bus_bus.id` is a per-database sequence, so the high-watermark
            // and the seen-id history from the previous DB are meaningless
            // (and likely higher / colliding) for the new one. Keeping them
            // would make the subscribe `last` bogus and the dedup filter drop
            // legitimate notifications whose ids happen to collide with
            // recently seen ids of the old DB. Reset both (and drop now-stale
            // queued messages that reference the old DB's channels) so the
            // fresh subscribe re-fetches from the correct baseline.
            this.lastNotificationId = 0;
            this.seenNotificationIds.clear();
            this.messageWaitQueue = [];
        }
        this.sendToClient(client, "BUS:WORKER_STATE_UPDATED", this.state);
        this.sendToClient(client, "BUS:INITIALIZED");
        if (!this.active) {
            this.sendToClient(client, "BUS:OUTDATED");
        }
    }

    /**
     * Determine whether or not the websocket associated to this worker
     * is connected.
     *
     * @returns {boolean}
     */
    _isWebsocketConnected() {
        return (
            this.websocket && this.websocket.readyState === WEBSOCKET_READY_STATE.OPEN
        );
    }

    /**
     * Determine whether or not the websocket associated to this worker
     * is connecting.
     *
     * @returns {boolean}
     */
    _isWebsocketConnecting() {
        return (
            this.websocket &&
            this.websocket.readyState === WEBSOCKET_READY_STATE.CONNECTING
        );
    }

    /**
     * Determine whether or not the websocket associated to this worker
     * is in the closing state.
     *
     * @returns {boolean}
     */
    _isWebsocketClosing() {
        return (
            this.websocket &&
            this.websocket.readyState === WEBSOCKET_READY_STATE.CLOSING
        );
    }

    /**
     * Triggered when a connection is closed. If closure was not clean ,
     * try to reconnect after indicating to the clients that the
     * connection was closed.
     *
     * @param {CloseEvent} ev
     * @param {number} code  close code indicating why the connection
     * was closed.
     * @param {string} reason reason indicating why the connection was
     * closed.
     */
    _onWebsocketClose({ code, reason }) {
        clearInterval(this._connectionCheckInterval);
        this._logDebug("_onWebsocketClose", code, reason);
        this._updateState(CONNECTION_STATE.DISCONNECTED);
        this.lastChannelSubscription = null;
        // Resolve before replacing: non-subscribe messages sent while the
        // connection was open (but before its first subscribe went out) are
        // chained on this deferred. Replacing an unresolved deferred would
        // orphan those callbacks and silently lose the messages; resolving it
        // is safe — the chained callback re-checks `_isWebsocketConnected()`
        // (false here) and re-queues into `messageWaitQueue` for next open.
        this.firstSubscribeDeferred.resolve();
        this.firstSubscribeDeferred = new Deferred();
        if (this.isReconnecting) {
            // Connection was not established but the close event was
            // triggered anyway. Let the onWebsocketError method handle
            // this case.
            return;
        }
        this.broadcast("BUS:DISCONNECT", { code, reason });
        if (code === WEBSOCKET_CLOSE_CODES.CLEAN) {
            if (reason === "OUTDATED_VERSION") {
                console.warn("Worker deactivated due to an outdated version.");
                this.active = false;
                this.broadcast("BUS:OUTDATED");
            }
            // WebSocket was closed on purpose, do not try to reconnect.
            return;
        }
        // WebSocket was not closed cleanly, let's try to reconnect.
        this.broadcast("BUS:RECONNECTING", { closeCode: code });
        this.isReconnecting = true;
        if (
            [
                WEBSOCKET_CLOSE_CODES.KEEP_ALIVE_TIMEOUT,
                WEBSOCKET_CLOSE_CODES.CLOSING_HANDSHAKE_ABORTED,
            ].includes(code)
        ) {
            // Don't wait to reconnect: keep-alive shouldn't be noticed, and the
            // closing handshake was aborted because the client explicitly tried
            // to connect while the socket was stuck in the closing state.
            this.connectRetryDelay = 0;
        }
        if (code === WEBSOCKET_CLOSE_CODES.SESSION_EXPIRED) {
            this.isWaitingForNewUID = true;
        }
        this._retryConnectionWithDelay();
    }

    /**
     * Triggered when a connection failed or failed to established.
     */
    _onWebsocketError() {
        this._logDebug("_onWebsocketError");
        this._retryConnectionWithDelay();
    }

    /**
     * Handle data received from the bus.
     *
     * @param {MessageEvent} messageEv
     */
    _onWebsocketMessage(messageEv) {
        this._restartConnectionCheckInterval();
        let payload;
        try {
            payload = JSON.parse(messageEv.data);
        } catch {
            // The server delivers notification batches as JSON. Anything else
            // (e.g. an echoed keepalive/control frame) is not ours: ignore it
            // rather than throwing out of the message listener.
            this._logDebug("_onWebsocketMessage: ignored non-JSON frame");
            return;
        }
        if (!Array.isArray(payload)) {
            // The server delivers notification batches as a JSON array. A frame
            // that is valid JSON but not an array (e.g. an echoed control frame)
            // is not a notification batch: ignore it rather than throwing out of
            // the message listener on `payload.filter`.
            this._logDebug("_onWebsocketMessage: ignored non-array frame");
            return;
        }
        // Drop any notification whose EXACT id was already processed. This
        // deliberately mirrors the server's own dedup semantics
        // (`NotificationDispatchState` in bus/websocket.py): notifications
        // committed out of id order by concurrent transactions are
        // re-delivered with LOWER ids in LATER batches during a hold-back
        // window (`MAX_NOTIFICATION_HISTORY_SEC`). A monotonic
        // `id > lastNotificationId` watermark would silently discard exactly
        // those late-committed notifications; only an id-level seen check is
        // both duplicate-safe and loss-free.
        const now = Date.now();
        this._pruneSeenNotificationIds(now);
        const notifications = payload.filter(
            (notification) => !this.seenNotificationIds.has(notification.id),
        );
        this._logDebug("_onWebsocketMessage", notifications);
        if (!notifications.length) {
            return;
        }
        for (const notification of notifications) {
            this.seenNotificationIds.set(notification.id, now);
        }
        // Track the greatest id seen (batches are not guaranteed ascending),
        // used only as the `last` value of (re)subscribes. Max is correct
        // there: within a connection the server ignores later `last` values
        // (`initialize_last_id` only adopts it while its own last_id is 0)
        // and holds its `last_id` back server-side for out-of-order commits;
        // on a fresh connection the server adopts it as the polling floor,
        // and any held-back lower ids it re-sends are handled by the
        // seen-id filter above.
        this.lastNotificationId = Math.max(
            this.lastNotificationId,
            ...notifications.map((notification) => notification.id),
        );
        this.broadcast("BUS:NOTIFICATION", notifications);
    }

    /**
     * Forget seen notification ids that are older than the retention window
     * (they can no longer be legitimately re-sent by the server), and cap the
     * map size defensively.
     *
     * @param {number} now
     */
    _pruneSeenNotificationIds(now) {
        // Insertion order == arrival order, so expired entries form a prefix.
        for (const [id, seenAt] of this.seenNotificationIds) {
            if (
                now - seenAt <= this.SEEN_NOTIFICATION_RETENTION_MS &&
                this.seenNotificationIds.size <= this.SEEN_NOTIFICATION_MAX_COUNT
            ) {
                break;
            }
            this.seenNotificationIds.delete(id);
        }
    }

    async _logDebug(title, ...args) {
        if (this.loggingEnabled) {
            try {
                await logger.log({
                    dt: new Date().toISOString(),
                    event: title,
                    args,
                    worker: UUID,
                });
            } catch (e) {
                console.error(e);
            }
        }
    }

    /**
     * Triggered on websocket open. Send message that were waiting for
     * the connection to open.
     */
    _onWebsocketOpen() {
        this._logDebug("_onWebsocketOpen");
        // Gate this connection's queued messages behind ITS OWN subscribe.
        // `_onWebsocketClose` resets this deferred, but a `_stop()`/`_start()`
        // cycle (e.g. offline→online) removes the socket listeners so close
        // never runs, leaving a stale *resolved* deferred. Without this reset
        // the queue would flush (next microtask) before the new subscribe is
        // sent (~300ms later, debounced), violating the ordering guarantee.
        // `_stop`/`_onWebsocketClose` both null `lastChannelSubscription`, so
        // the subscribe below is always (re)sent and resolves this deferred.
        this.firstSubscribeDeferred = new Deferred();
        // Force a fresh subscribe on every (re)connect. `_onWebsocketClose` and
        // `_stop` null this, but a channel add/remove *during* the disconnect
        // re-populates it (the debounced `_updateChannels` runs while offline and
        // sets it to the current channel set). The open-time
        // `_debouncedUpdateChannels()` below would then find the channels
        // unchanged, send no subscribe and never resolve `firstSubscribeDeferred`
        // -- leaving the queued subscribe (and every queued app message) stuck in
        // `messageWaitQueue` on a connected-but-unsubscribed socket, silently
        // dropping all notifications until the next channel change. Nulling here
        // restores the "always re-subscribe on open" invariant.
        this.lastChannelSubscription = null;
        this._updateState(CONNECTION_STATE.CONNECTED);
        this.broadcast(this.isReconnecting ? "BUS:RECONNECT" : "BUS:CONNECT");
        this._debouncedUpdateChannels();
        this.connectRetryDelay = this.INITIAL_RECONNECT_DELAY;
        // Actually cancel any pending retry, don't just drop the handle: an
        // orphaned timer would survive a later BUS:STOP (offline), fire,
        // reconnect the stopped worker, and — through the error path — re-arm
        // itself forever.
        clearTimeout(this.connectTimeout);
        this.connectTimeout = null;
        this.isReconnecting = false;
        this.firstSubscribeDeferred.then(() => {
            if (!this._isWebsocketConnected()) {
                // Socket already closed/replaced: keep the queue for the
                // next open instead of writing to a dead socket.
                return;
            }
            // Drop queued subscribes: the deferred only resolves once
            // `_updateChannels` sent a fresh subscribe for THIS connection,
            // so any subscribe still queued (from the offline period) is
            // stale — replaying it would rewind the subscription and make
            // the server re-poll for nothing.
            const queue = this.messageWaitQueue.filter(
                (msg) => JSON.parse(msg).event_name !== "subscribe",
            );
            this.messageWaitQueue = [];
            queue.forEach((msg) => this.websocket.send(msg));
        });
        this._restartConnectionCheckInterval();
    }

    /**
     * Sends a custom application-level message to perform a connection check
     * on the WebSocket.
     *
     * Browsers rely on the OS's TCP mechanism, which can take minutes or
     * hours to detect a dead connection. Sending data triggers an immediate
     * I/O operation, quickly revealing any network-level failure. This must be
     * implemented at the application level because the browser WebSocket API
     * does not expose the built-in ping/pong mechanism.
     */
    _restartConnectionCheckInterval() {
        clearInterval(this._connectionCheckInterval);
        this._connectionCheckInterval = setInterval(() => {
            if (this._isWebsocketConnected()) {
                this.websocket.send(new Uint8Array([0x00]));
                this._logDebug("connection_checked");
            }
        }, this.CONNECTION_CHECK_DELAY);
    }

    /**
     * Try to reconnect to the server, an exponential back off is
     * applied to the reconnect attempts.
     */
    _retryConnectionWithDelay() {
        // Cancel any pending retry first: a failed connection fires both
        // `error` and `close`, each of which schedules a retry. Without this,
        // the first timer would be orphaned (untracked by `connectTimeout`,
        // so uncancellable by `_stop`), leaking a zombie reconnect.
        clearTimeout(this.connectTimeout);
        // `connectRetryDelay` is the jitter-free exponential base: keeping
        // jitter out of it stops the base from drifting and makes
        // MAXIMUM_RECONNECT_DELAY a true ceiling. Jitter is added only to the
        // armed timer. A base of 0 means "reconnect immediately" (set on
        // keep-alive/aborted closes) and skips jitter — but the base is then
        // advanced to INITIAL so a persistently failing socket backs off
        // normally instead of hot-looping at delay 0. Exponential growth only
        // starts from INITIAL: after the 0-delay fast path the next delay is
        // exactly INITIAL_RECONNECT_DELAY, not INITIAL * 1.5.
        const delay =
            this.connectRetryDelay === 0
                ? 0
                : this.connectRetryDelay + this.RECONNECT_JITTER * Math.random();
        this.connectRetryDelay =
            this.connectRetryDelay === 0
                ? this.INITIAL_RECONNECT_DELAY
                : Math.min(this.connectRetryDelay * 1.5, MAXIMUM_RECONNECT_DELAY);
        this._logDebug("_retryConnectionWithDelay", delay);
        this.connectTimeout = setTimeout(this._start.bind(this), delay);
    }

    /**
     * Send a message to the server through the websocket connection.
     * If the websocket is not open, enqueue the message and send it
     * upon the next reconnection.
     *
     * @param {{event_name: string, data: any }} message Message to send to the server.
     */
    _sendToServer(message) {
        this._logDebug("_sendToServer", message);
        const payload = JSON.stringify(message);
        if (!this._isWebsocketConnected()) {
            if (message["event_name"] === "subscribe") {
                this.messageWaitQueue = this.messageWaitQueue.filter(
                    (msg) => JSON.parse(msg).event_name !== "subscribe",
                );
                this.messageWaitQueue.unshift(payload);
            } else {
                this.messageWaitQueue.push(payload);
            }
        } else {
            if (message["event_name"] === "subscribe") {
                this.websocket.send(payload);
            } else {
                this.firstSubscribeDeferred.then(() => {
                    // The deferred can resolve after the connection state
                    // changed: `_updateChannels` also resolves it while
                    // offline/stopped (queued subscribe), at which point
                    // `this.websocket` may be null or closed. Re-queue the
                    // message for the next open instead of crashing with an
                    // unhandled rejection and losing it.
                    if (this._isWebsocketConnected()) {
                        this.websocket.send(payload);
                    } else {
                        this.messageWaitQueue.push(payload);
                    }
                });
            }
            this._restartConnectionCheckInterval();
        }
    }

    _removeWebsocketListeners() {
        this.websocket?.removeEventListener("open", this._onWebsocketOpen);
        this.websocket?.removeEventListener("message", this._onWebsocketMessage);
        this.websocket?.removeEventListener("error", this._onWebsocketError);
        this.websocket?.removeEventListener("close", this._onWebsocketClose);
    }

    /**
     * Start the worker by opening a websocket connection.
     */
    _start() {
        this._logDebug("_start");
        if (
            !this.active ||
            this._isWebsocketConnected() ||
            this._isWebsocketConnecting()
        ) {
            return;
        }
        this._removeWebsocketListeners();
        if (this._isWebsocketClosing()) {
            // The close event didn’t trigger. Trigger manually to maintain
            // correct state and lifecycle handling.
            const wasReconnecting = this.isReconnecting;
            this._onWebsocketClose(
                new CloseEvent("close", {
                    code: WEBSOCKET_CLOSE_CODES.CLOSING_HANDSHAKE_ABORTED,
                }),
            );
            this.websocket = null;
            if (wasReconnecting) {
                // `_onWebsocketClose` early-returns while reconnecting because
                // it expects a real `error` event to drive the retry — but this
                // synthetic close has none. Schedule the retry explicitly so
                // the reconnect loop doesn't stall until an external BUS:START.
                this._retryConnectionWithDelay();
            }
            return;
        }
        this._updateState(CONNECTION_STATE.CONNECTING);
        this.websocket = new WebSocket(this.websocketURL);
        this.websocket.addEventListener("open", this._onWebsocketOpen);
        this.websocket.addEventListener("error", this._onWebsocketError);
        this.websocket.addEventListener("message", this._onWebsocketMessage);
        this.websocket.addEventListener("close", this._onWebsocketClose);
    }

    /**
     * Stop the worker.
     */
    _stop() {
        this._logDebug("_stop");
        clearTimeout(this.connectTimeout);
        // `_stop` removes the socket listeners below, so `_onWebsocketClose`
        // (the other place clearing this interval) will not run: clear it here
        // to avoid leaking a timer on every stop cycle.
        clearInterval(this._connectionCheckInterval);
        // Cancel pending debounced work so it can't fire against the *next*
        // connection: a trailing `_updateChannels` would enqueue a stray
        // subscribe and prematurely resolve `firstSubscribeDeferred`, and a
        // trailing `_sendToServer` would leak an app message into the queue.
        this._debouncedUpdateChannels.cancel();
        this._debouncedSendToServer.cancel();
        this._forceUpdateChannels.cancel();
        this.connectRetryDelay = this.INITIAL_RECONNECT_DELAY;
        this.isReconnecting = false;
        this.lastChannelSubscription = null;
        const shouldBroadcastClose =
            this.websocket &&
            this.websocket.readyState !== WEBSOCKET_READY_STATE.CLOSED;
        this.websocket?.close();
        this._removeWebsocketListeners();
        this.websocket = null;
        // `_stop` removed the socket listeners, so `_onWebsocketClose` (which
        // resolves the deferred and reports DISCONNECTED) will not run. Do
        // both here: an unresolved deferred would orphan pending sends
        // chained on it (the socket is already nulled, so they re-queue into
        // `messageWaitQueue`), and a state left on CONNECTED would make
        // `_initializeConnection` report a live connection to tabs opened
        // while stopped.
        this.firstSubscribeDeferred.resolve();
        this._updateState(CONNECTION_STATE.DISCONNECTED);
        if (shouldBroadcastClose) {
            this.broadcast("BUS:DISCONNECT", { code: WEBSOCKET_CLOSE_CODES.CLEAN });
        }
    }

    /**
     * Update the channel subscription on the server. Ignore if the channels
     * did not change since the last subscription.
     *
     * @param {boolean} force Whether or not we should update the subscription
     * event if the channels haven't change since last subscription.
     */
    _updateChannels({ force = false } = {}) {
        const allTabsChannels = this._getAllChannels();
        const allTabsChannelsString = JSON.stringify(allTabsChannels);
        const shouldUpdateChannelSubscription =
            allTabsChannelsString !== this.lastChannelSubscription;
        if (force || shouldUpdateChannelSubscription) {
            this.lastChannelSubscription = allTabsChannelsString;
            this._sendToServer({
                event_name: "subscribe",
                data: { channels: allTabsChannels, last: this.lastNotificationId },
            });
            this.firstSubscribeDeferred.resolve();
        }
    }
    /**
     * Update the worker state and broadcast the new state to its clients.
     *
     * @param {CONNECTION_STATE[keyof CONNECTION_STATE]} newState
     */
    _updateState(newState) {
        this.state = newState;
        this.broadcast("BUS:WORKER_STATE_UPDATED", newState);
    }
}
