/** @odoo-module native */
import { WORKER_STATE } from "@bus/services/worker_service";
import { EventBus, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";
import { session } from "@web/session";

// Worker events consumed internally by this service and NOT re-triggered on
// the public bus. Everything else is only rebroadcast when it is an
// application-level `BUS:` event: the worker port also carries ELECTION:*
// (main-tab election heartbeats, every 1.5s) and BASE:* traffic, which must
// never leak onto the app bus as events.
const INTERNAL_EVENTS = new Set([
    "BUS:INITIALIZED",
    "BUS:NOTIFICATION",
    // Handled by bus.logs_service through its own worker handler.
    "BUS:PROVIDE_LOGS",
    // Liveness probe, answered by worker_service — not an application event.
    "BUS:PING",
]);
// Trailing delay before persisting the notification watermark to
// localStorage. Writing on every batch in every tab costs N synchronous
// writes plus N×(N-1) cross-tab `storage` events; the watermark's consumers
// (fresh-worker seeding, which the worker maxes with its own live value
// anyway, and the outdated-page watcher, which compares against the server's
// multi-day GC horizon) tolerate a sub-second-stale value just fine.
const WATERMARK_WRITE_DELAY = 500;
// Slightly delay the reconnection when coming back online as the network is not
// ready yet and the exponential backoff would delay the reconnection by a lot.
export const BACK_ONLINE_RECONNECT_DELAY = 5000;
/**
 * Key of the cross-tab shared value holding the highest notification id seen.
 *
 * Scoped by database: `bus_bus.id` is a per-database sequence, so a watermark
 * from another database on the same origin (common on dev/staging hosts) would
 * seed a fresh worker with a bogus `last`, silently dropping every
 * notification until the new database's sequence catches up.
 */
export function lastNotificationIdKey() {
    return `${session.db}.last_notification_id`;
}
/**
 * Communicate with a SharedWorker in order to provide a single websocket
 * connection shared across multiple tabs.
 *
 *  @emits BUS:CONNECT
 *  @emits BUS:DISCONNECT
 *  @emits BUS:RECONNECT
 *  @emits BUS:RECONNECTING
 *  @emits BUS:WORKER_STATE_UPDATED
 */
export const busService = {
    dependencies: [
        "bus.parameters",
        "localization",
        "multi_tab",
        "legacy_multi_tab",
        "worker_service",
    ],

    start(
        env,
        {
            multi_tab: multiTab,
            legacy_multi_tab: legacyMultiTab,
            "bus.parameters": params,
            worker_service: workerService,
        },
    ) {
        const bus = new EventBus();
        const notificationBus = new EventBus();
        const subscribeFnToWrapper = new Map();
        let backOnlineTimeout;
        let watermarkWriteTimeout;
        const startedAt = luxon.DateTime.now().set({ milliseconds: 0 });
        let connectionInitializedDeferred;
        // Whether this tab's BUS:INITIALIZED handshake completed. Channel
        // operations issued before that are replayed as one atomic snapshot
        // instead of incremental messages (see the BUS:INITIALIZED case).
        let workerInitialized = false;
        // Whether this tab sent BUS:LEAVE (stop()) since it last pushed its
        // channels to the worker: the worker dropped the client, so the next
        // start()/addChannel() must replay the full channel map.
        let hasLeftWorker = false;

        /**
         * Persist the highest notification id seen by this tab, debounced and
         * write-if-newer: all tabs receive the same batches within
         * milliseconds of each other, so after the first tab's write the
         * others find the stored value up to date and skip their own write
         * (reads don't fire cross-tab `storage` events).
         */
        function scheduleWatermarkWrite() {
            if (watermarkWriteTimeout) {
                return;
            }
            watermarkWriteTimeout = browser.setTimeout(() => {
                watermarkWriteTimeout = null;
                const stored = legacyMultiTab.getSharedValue(
                    lastNotificationIdKey(),
                    0,
                );
                if (stored < state.lastNotificationId) {
                    legacyMultiTab.setSharedValue(
                        lastNotificationIdKey(),
                        state.lastNotificationId,
                    );
                }
            }, WATERMARK_WRITE_DELAY);
        }

        /**
         * Handle messages received from the shared worker and fires an
         * event according to the message type.
         *
         * @param {MessageEvent} messageEv
         * @param {{type: WorkerEvent, data: any}[]}  messageEv.data
         */
        function handleMessage(messageEv) {
            const { type, data } = messageEv.data;
            switch (type) {
                case "BUS:NOTIFICATION": {
                    const notifications = data.map(({ id, message }) => ({
                        id,
                        ...message,
                    }));
                    if (!notifications.length) {
                        break;
                    }
                    // Highest id of the batch, not `.at(-1)`: the worker
                    // deliberately does not assume server batches arrive in
                    // ascending id order (see `_onWebsocketMessage`). Max with
                    // the current value: the worker may also legitimately
                    // deliver LOWER ids in later batches (late-committed
                    // notifications inside the server's hold-back window).
                    state.lastNotificationId = Math.max(
                        state.lastNotificationId ?? 0,
                        ...notifications.map(({ id }) => id),
                    );
                    scheduleWatermarkWrite();
                    for (const { id, type, payload } of notifications) {
                        notificationBus.trigger(type, { id, payload });
                        busService._onMessage(env, id, type, payload);
                    }
                    break;
                }
                case "BUS:INITIALIZED": {
                    // Channels claimed while the worker was initializing were
                    // NOT sent incrementally (see addChannel/deleteChannel):
                    // interleaved adds/deletes racing the init handshake can
                    // reach the worker out of balance. One atomic snapshot of
                    // the final map — sent before the pending calls resume
                    // (the resolve below only schedules microtasks) — cannot
                    // drift.
                    workerInitialized = true;
                    if (tabChannels.size) {
                        sendChannelsSnapshot();
                    }
                    connectionInitializedDeferred.resolve();
                    break;
                }
                case "BUS:WORKER_STATE_UPDATED":
                    state.workerState = data;
                    break;
                case "BUS:OUTDATED":
                    // Only the multi-tab bookkeeping happens here: a tab
                    // running outdated code must permanently renounce
                    // main-tab duties. The user-facing "page is out of date"
                    // notification is owned by OutdatedPageWatcherService
                    // (single deduped toast, whichever trigger fires first),
                    // which listens to the rebroadcast below.
                    multiTab.unregister();
                    break;
            }
            // Allowlist rebroadcast: the port also carries ELECTION:*/BASE:*
            // frames (election heartbeats every 1.5s), which must not surface
            // as application events.
            if (type?.startsWith("BUS:") && !INTERNAL_EVENTS.has(type)) {
                bus.trigger(type, data);
            }
        }

        /**
         * Start the "bus_service" workerService.
         */
        async function ensureWorkerStarted() {
            if (!connectionInitializedDeferred) {
                connectionInitializedDeferred = new Deferred();
                let uid = Array.isArray(session.user_id)
                    ? session.user_id[0]
                    : user.userId;
                if (!uid && uid !== undefined) {
                    uid = false;
                }
                await workerService.ensureWorkerStarted();
                if (workerService.state === WORKER_STATE.FAILED) {
                    // The worker could not be created (e.g. cross-origin
                    // bundle fetch failed in prefork mode without a proxy).
                    // worker_service already degrades to no-op sends/handlers,
                    // so no BUS:INITIALIZED will ever arrive. Unblock our own
                    // callers instead of awaiting a deferred that never
                    // resolves (which would hang addChannel/start/subscribe).
                    connectionInitializedDeferred.resolve();
                    return;
                }
                await workerService.registerHandler(handleMessage);
                workerService.send("BUS:INITIALIZE_CONNECTION", {
                    websocketURL: `${params.serverURL.replace("http", "ws")}/websocket?version=${
                        session.websocket_worker_version
                    }`,
                    db: session.db,
                    debug: odoo.debug,
                    lastNotificationId: legacyMultiTab.getSharedValue(
                        lastNotificationIdKey(),
                        0,
                    ),
                    uid,
                    startTs: startedAt.valueOf(),
                });
            }
            await connectionInitializedDeferred;
        }

        // Channels claimed by this tab's consumers, REFCOUNTED (channel ->
        // claim count): several independent features may add/delete the same
        // channel (e.g. two im_livechat features in one tab), and each delete
        // must only release its own claim — a Set would conflate them and the
        // first delete would kill the channel for the remaining consumers.
        // The worker mirrors this refcounting per client. Also needed to
        // replay the subscription after a bfcache restore: a long-frozen tab
        // may have been evicted by the worker's liveness sweep (its JS cannot
        // answer BUS:PING while frozen), losing its channel map worker-side.
        const tabChannels = new Map();

        /**
         * Atomically replace this client's channel claims worker-side with
         * the current local map. A snapshot (rather than replaying
         * incremental adds) cannot drift from in-flight add/delete messages:
         * every local mutation is applied synchronously to `tabChannels`
         * before any message is sent, so by the time the snapshot is
         * enqueued it already accounts for every message enqueued before it,
         * and later messages apply incrementally on top of it.
         */
        function sendChannelsSnapshot() {
            workerService.send("BUS:SET_CHANNELS", [...tabChannels]);
        }

        browser.addEventListener("pagehide", ({ persisted }) => {
            if (!persisted) {
                // Page is gonna be unloaded, disconnect this client
                // from the worker.
                workerService.send("BUS:LEAVE");
            }
        });
        browser.addEventListener("pageshow", ({ persisted }) => {
            if (persisted && state.isActive) {
                // Restored from bfcache: replay our channel claims with their
                // refcounts. Harmless when the worker still knows us (an
                // unchanged aggregate set sends no new subscribe); required
                // when the liveness sweep evicted us while frozen.
                sendChannelsSnapshot();
                workerService.send("BUS:START");
            }
        });
        browser.addEventListener(
            "online",
            () => {
                // Two `online` events with no intervening `offline` would
                // otherwise orphan the first timer (it still fires a redundant
                // BUS:START); clear it before rescheduling. `browser.`-prefixed
                // like the matching `browser.setTimeout`, so mocked clocks see
                // (and can assert) the cancellation too.
                browser.clearTimeout(backOnlineTimeout);
                backOnlineTimeout = browser.setTimeout(() => {
                    if (state.isActive) {
                        workerService.send("BUS:START");
                    }
                }, BACK_ONLINE_RECONNECT_DELAY);
            },
            { capture: true },
        );
        browser.addEventListener(
            "offline",
            () => {
                browser.clearTimeout(backOnlineTimeout);
                workerService.send("BUS:STOP");
            },
            {
                capture: true,
            },
        );
        const state = reactive({
            addEventListener: bus.addEventListener.bind(bus),
            addChannel: async (channel) => {
                tabChannels.set(channel, (tabChannels.get(channel) ?? 0) + 1);
                if (workerInitialized) {
                    if (hasLeftWorker) {
                        // First channel activity after a stop(): the worker
                        // dropped this client on BUS:LEAVE, so replay the
                        // whole map, not just this claim.
                        sendChannelsSnapshot();
                        hasLeftWorker = false;
                    } else {
                        workerService.send("BUS:ADD_CHANNEL", channel);
                    }
                    workerService.send("BUS:START");
                    state.isActive = true;
                    return;
                }
                // Worker (still) initializing: do NOT send an incremental add
                // — interleaved adds/deletes racing the init handshake could
                // reach the worker out of balance. The claim is included in
                // the atomic BUS:SET_CHANNELS snapshot sent on
                // BUS:INITIALIZED; only the connection wake-up remains to do
                // here.
                await ensureWorkerStarted();
                if (!(tabChannels.get(channel) > 0)) {
                    // Every claim on this channel was released (deleteChannel)
                    // while the worker was initializing: don't activate the
                    // bus on behalf of a dead claim.
                    return;
                }
                workerService.send("BUS:START");
                state.isActive = true;
            },
            deleteChannel: (channel) => {
                const count = tabChannels.get(channel) ?? 0;
                if (count <= 0) {
                    // Refcount must never go negative: an extra delete from
                    // one consumer would otherwise steal a later legitimate
                    // claim of another one.
                    console.warn(
                        `bus_service: deleteChannel("${channel}") without a matching addChannel.`,
                    );
                    return;
                }
                if (count === 1) {
                    tabChannels.delete(channel);
                } else {
                    tabChannels.set(channel, count - 1);
                }
                if (!workerInitialized) {
                    // Released before/during worker init: the release is
                    // already reflected in the BUS:SET_CHANNELS snapshot the
                    // init handshake sends (or nothing was ever sent for this
                    // channel if the worker never starts).
                    return;
                }
                workerService.send("BUS:DELETE_CHANNEL", channel);
            },
            setLoggingEnabled: (isEnabled) =>
                workerService.send("BUS:SET_LOGGING_ENABLED", isEnabled),
            downloadLogs: () => workerService.send("BUS:REQUEST_LOGS"),
            forceUpdateChannels: () => workerService.send("BUS:FORCE_UPDATE_CHANNELS"),
            trigger: bus.trigger.bind(bus),
            removeEventListener: bus.removeEventListener.bind(bus),
            send: (eventName, data) =>
                workerService.send("BUS:SEND", { event_name: eventName, data }),
            start: async () => {
                await ensureWorkerStarted();
                // Replay this tab's channel claims: after a stop() the worker
                // dropped this client (BUS:LEAVE) along with its channel map,
                // and without the replay a stop()/start() cycle would lose
                // every subscription of this tab. Harmless otherwise — the
                // snapshot matches what the worker already has.
                if (tabChannels.size || hasLeftWorker) {
                    sendChannelsSnapshot();
                    hasLeftWorker = false;
                }
                workerService.send("BUS:START");
                state.isActive = true;
            },
            stop: () => {
                workerService.send("BUS:LEAVE");
                hasLeftWorker = true;
                state.isActive = false;
            },
            isActive: false,
            /**
             * Subscribe to a single notification type. Idempotent: subscribing
             * the same (type, callback) pair again is a no-op — it must NOT
             * add a second live listener while overwriting the only wrapper
             * handle in the map, which would leave the first listener firing
             * forever with no way to unsubscribe it.
             *
             * @param {string} notificationType
             * @param {function} callback
             */
            subscribe(notificationType, callback) {
                // Key by (callback, notificationType): a single callback may be
                // subscribed to several types, so one wrapper per type must be
                // kept, otherwise unsubscribe would remove the wrong listener
                // and leak the others.
                if (!subscribeFnToWrapper.has(callback)) {
                    subscribeFnToWrapper.set(callback, new Map());
                }
                const wrappersByType = subscribeFnToWrapper.get(callback);
                if (wrappersByType.has(notificationType)) {
                    return;
                }
                const wrapper = ({ detail }) => {
                    const { id, payload } = detail;
                    // Per-subscriber isolation: each callback gets its own
                    // deep copy, so one subscriber mutating the payload cannot
                    // corrupt what the others see. `structuredClone` rather
                    // than a JSON round-trip: same isolation guarantee (the
                    // payload comes out of `JSON.parse` in the worker, so it
                    // is plain data), meaningfully cheaper per call, and a
                    // once-per-notification shared clone would silently drop
                    // the isolation semantics subscribers rely on today.
                    callback(structuredClone(payload), { id });
                };
                wrappersByType.set(notificationType, wrapper);
                notificationBus.addEventListener(notificationType, wrapper);
            },
            /**
             * Unsubscribe from a single notification type.
             *
             * @param {string} notificationType
             * @param {function} callback
             */
            unsubscribe(notificationType, callback) {
                const wrappersByType = subscribeFnToWrapper.get(callback);
                const wrapper = wrappersByType?.get(notificationType);
                if (!wrapper) {
                    return;
                }
                notificationBus.removeEventListener(notificationType, wrapper);
                wrappersByType.delete(notificationType);
                if (wrappersByType.size === 0) {
                    subscribeFnToWrapper.delete(callback);
                }
            },
            startedAt,
            workerState: null,
            /** The id of the last notification received by this tab. */
            lastNotificationId: null,
        });
        return state;
    },
    /** Overriden to provide logs in tests. Use subscribe() in production. */
    _onMessage(env, id, type, payload) {},
};
registry.category("services").add("bus_service", busService);
