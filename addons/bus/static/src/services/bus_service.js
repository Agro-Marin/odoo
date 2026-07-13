/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { EventBus, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";
import { session } from "@web/session";
import { WORKER_STATE } from "@bus/services/worker_service";

// List of worker events that should not be broadcasted.
const INTERNAL_EVENTS = new Set([
    "BUS:INITIALIZED",
    "BUS:OUTDATED",
    "BUS:NOTIFICATION",
    "BUS:PROVIDE_LOGS",
    // Liveness probe, answered by worker_service — not an application event.
    "BUS:PING",
]);
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
        "notification",
        "worker_service",
    ],

    start(
        env,
        {
            multi_tab: multiTab,
            legacy_multi_tab: legacyMultiTab,
            notification,
            "bus.parameters": params,
            worker_service: workerService,
        },
    ) {
        const bus = new EventBus();
        const notificationBus = new EventBus();
        const subscribeFnToWrapper = new Map();
        let backOnlineTimeout;
        const startedAt = luxon.DateTime.now().set({ milliseconds: 0 });
        let connectionInitializedDeferred;

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
                case "BUS:PROVIDE_LOGS": {
                    const blob = new Blob([JSON.stringify(data, null, 2)], {
                        type: "application/json",
                    });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `bus_logs_${luxon.DateTime.now().toFormat(
                        "yyyy-LL-dd-HH-mm-ss",
                    )}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                    break;
                }
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
                    // ascending id order (see `_onWebsocketMessage`).
                    state.lastNotificationId = Math.max(
                        ...notifications.map(({ id }) => id),
                    );
                    legacyMultiTab.setSharedValue(
                        lastNotificationIdKey(),
                        state.lastNotificationId,
                    );
                    for (const { id, type, payload } of notifications) {
                        notificationBus.trigger(type, { id, payload });
                        busService._onMessage(env, id, type, payload);
                    }
                    break;
                }
                case "BUS:INITIALIZED": {
                    connectionInitializedDeferred.resolve();
                    break;
                }
                case "BUS:WORKER_STATE_UPDATED":
                    state.workerState = data;
                    break;
                case "BUS:OUTDATED": {
                    multiTab.unregister();
                    notification.add(
                        _t(
                            "Save your work and refresh to get the latest updates and avoid potential issues.",
                        ),
                        {
                            title: _t("The page is out of date"),
                            type: "warning",
                            sticky: true,
                            buttons: [
                                {
                                    name: _t("Refresh"),
                                    primary: true,
                                    onClick: () => {
                                        browser.location.reload();
                                    },
                                },
                            ],
                        },
                    );
                    break;
                }
            }
            if (!INTERNAL_EVENTS.has(type)) {
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

        // Channels this tab forwarded to the worker. Needed to replay the
        // subscription after a bfcache restore: a long-frozen tab may have
        // been evicted by the worker's liveness sweep (its JS cannot answer
        // BUS:PING while frozen), losing its channel list worker-side.
        const tabChannels = new Set();
        browser.addEventListener("pagehide", ({ persisted }) => {
            if (!persisted) {
                // Page is gonna be unloaded, disconnect this client
                // from the worker.
                workerService.send("BUS:LEAVE");
            }
        });
        browser.addEventListener("pageshow", ({ persisted }) => {
            if (persisted && state.isActive) {
                // Restored from bfcache: re-send our channels. Harmless when
                // the worker still knows us (per-client channel lists are
                // deduplicated and an unchanged set sends no new subscribe);
                // required when the liveness sweep evicted us while frozen.
                for (const channel of tabChannels) {
                    workerService.send("BUS:ADD_CHANNEL", channel);
                }
                workerService.send("BUS:START");
            }
        });
        browser.addEventListener(
            "online",
            () => {
                // Two `online` events with no intervening `offline` would
                // otherwise orphan the first timer (it still fires a redundant
                // BUS:START); clear it before rescheduling.
                clearTimeout(backOnlineTimeout);
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
                clearTimeout(backOnlineTimeout);
                workerService.send("BUS:STOP");
            },
            {
                capture: true,
            },
        );
        const state = reactive({
            addEventListener: bus.addEventListener.bind(bus),
            addChannel: async (channel) => {
                tabChannels.add(channel);
                await ensureWorkerStarted();
                if (!tabChannels.has(channel)) {
                    // deleteChannel() was called while the worker was
                    // initializing: its BUS:DELETE_CHANNEL was dropped by
                    // `worker_service.send` (pre-init sends are ignored), so
                    // sending the add now would subscribe a dead channel.
                    return;
                }
                workerService.send("BUS:ADD_CHANNEL", channel);
                workerService.send("BUS:START");
                state.isActive = true;
            },
            deleteChannel: (channel) => {
                tabChannels.delete(channel);
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
                workerService.send("BUS:START");
                state.isActive = true;
            },
            stop: () => {
                workerService.send("BUS:LEAVE");
                state.isActive = false;
            },
            isActive: false,
            /**
             * Subscribe to a single notification type.
             *
             * @param {string} notificationType
             * @param {function} callback
             */
            subscribe(notificationType, callback) {
                const wrapper = ({ detail }) => {
                    const { id, payload } = detail;
                    callback(JSON.parse(JSON.stringify(payload)), { id });
                };
                // Key by (callback, notificationType): a single callback may be
                // subscribed to several types, so one wrapper per type must be
                // kept, otherwise unsubscribe would remove the wrong listener
                // and leak the others.
                if (!subscribeFnToWrapper.has(callback)) {
                    subscribeFnToWrapper.set(callback, new Map());
                }
                subscribeFnToWrapper.get(callback).set(notificationType, wrapper);
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
