/** @odoo-module native */

/* global idbKeyval, PUSH_NOTIFICATION_ACTION, arrayBufferToBase64Url, planPushNotification, notificationTargetPath */
/**
 * @type {ServiceWorkerGlobalScope}
 */
const sw = /** @type {any} */ (self);

importScripts("/mail/static/lib/idb-keyval/idb-keyval.js");

const MESSAGE_TYPE = {
    POST_RTC_LOGS: "POST_RTC_LOGS",
};

const { Store, set, get } = idbKeyval;
const LOG_AGE_LIMIT = 24 * 60 * 60 * 1000;
/** @type {IDBDatabase|undefined} */
let db;
/** @type {Promise<IDBDatabase>|undefined} */
let dbPromise;
const unread_store = new Store("odoo-mail-unread-db", "odoo-mail-unread-store");
let interactionSinceCleanupCount = 0;

function openDatabase() {
    dbPromise ??= new Promise((resolve, reject) => {
        const request = indexedDB.open("RtcLogsDB", 1);
        request.onupgradeneeded = /** @param {IDBVersionChangeEvent} event */ function (
            event,
        ) {
            const db = event.target.result;
            if (!db.objectStoreNames.contains("logs")) {
                const store = db.createObjectStore("logs", {
                    keyPath: "id",
                    autoIncrement: true,
                });
                store.createIndex("timestamp", "timestamp", { unique: false });
            }
        };
        request.onsuccess = /** @param {Event} event */ async function (event) {
            db = event.target.result;
            try {
                await cleanupLogs(db);
            } catch (error) {
                console.error("Error cleaning up logs:", error);
            }
            resolve(db);
        };
        request.onerror = /** @param {Event} event */ function (event) {
            dbPromise = undefined;
            reject(event.target.error);
        };
    });
    return dbPromise;
}

sw.addEventListener("install", () => {
    sw.skipWaiting();
});

sw.addEventListener(
    "activate",
    /** @param {ExtendableEvent} event */ (event) => {
        event.waitUntil(Promise.all([openDatabase(), sw.clients.claim()]));
    },
);

/**
 * @param {IDBDatabase} dataBase
 * @returns {Promise<void>}
 */
async function cleanupLogs(dataBase) {
    const cutoffTime = Date.now() - LOG_AGE_LIMIT;
    return new Promise((resolve, reject) => {
        const tx = dataBase.transaction("logs", "readwrite");
        const store = tx.objectStore("logs");
        const index = store.index("timestamp");
        const range = IDBKeyRange.upperBound(cutoffTime);
        const request = index.openCursor(range);
        request.onsuccess = /** @param {Event} event */ (event) => {
            const cursor = event.target.result;
            if (cursor) {
                cursor.delete();
                cursor.continue();
            }
        };
        request.onerror = /** @param {Event} event */ (event) =>
            reject(event.target.error);
        tx.oncomplete = () => resolve();
        tx.onerror = /** @param {Event} event */ (event) => reject(event.target.error);
    });
}

/**
 * @param {Array<{type: string, entry: string, value: any}|undefined>} logs
 * @param {Object} [options]
 * @param {boolean} [options.download=false]
 * @returns {Promise<{timelines: Object, snapshots: Object}|undefined>}
 */
async function storeLogs(logs, { download = false } = {}) {
    if (!db) {
        await openDatabase();
    }
    if (interactionSinceCleanupCount > 30) {
        interactionSinceCleanupCount = 0;
        await cleanupLogs(db);
    }
    interactionSinceCleanupCount++;
    return new Promise((resolve, reject) => {
        let output;
        const tx = db.transaction("logs", "readwrite");
        const store = tx.objectStore("logs");
        for (const log of logs) {
            if (!log) {
                continue;
            }
            const { type, entry, value } = log;
            const request = store.add({
                type: type,
                entry: entry,
                value: value,
                timestamp: Date.now(),
            });
            request.onerror = /** @param {Event} event */ (event) =>
                reject(event.target.error);
        }
        if (download) {
            const request = store.getAll();
            request.onerror = /** @param {Event} event */ (event) =>
                reject(event.target.error);
            request.onsuccess = () => {
                const allLogs = request.result;
                const timelines = {};
                const snapshots = {};
                allLogs.forEach((log) => {
                    if (log.type === "timeline") {
                        timelines[log.entry] = log.value;
                    } else if (log.type === "snapshot") {
                        snapshots[log.entry] = log.value;
                    }
                });
                output = { timelines, snapshots };
            };
        }
        tx.oncomplete = () => resolve(output);
        tx.onerror = /** @param {Event} event */ (event) => reject(event.target.error);
    });
}

/**
 * @param {number} channelId
 * @param {Object} param1
 * @param {string} [param1.action]
 * @param {boolean} [param1.joinCall]
 * @param {Client | ServiceWorker | MessagePort} [source]
 */
async function openDiscussChannel(
    channelId,
    { action, joinCall = false, source } = {},
) {
    const discussURLRegexes = [new RegExp("/odoo/discuss")];
    if (action) {
        discussURLRegexes.push(
            new RegExp(`/odoo/\\d+/action-${action}`),
            new RegExp(`/odoo/action-${action}`),
        );
    }
    /**
     * @param {WindowClient} client
     * @returns {number}
     */
    const getScore = (client) =>
        (client.focused ? 4 : 0) +
        (client.visibilityState === "visible" ? 2 : 0) +
        (discussURLRegexes.some((r) => r.test(new URL(client.url).pathname)) ? 1 : 0);
    let targetClient;
    for (const client of await sw.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
    })) {
        if (source && source.id === client.id) {
            continue;
        }
        if (!targetClient || getScore(client) > getScore(targetClient)) {
            targetClient = client;
        }
    }
    if (targetClient) {
        targetClient.postMessage({
            action: "OPEN_CHANNEL",
            data: { id: channelId, joinCall },
        });
        targetClient.focus().catch(() => {});
        return;
    }
    const url = action
        ? new URL(`/odoo/action-${action}`, location.origin)
        : new URL("/odoo/discuss", location.origin);
    url.searchParams.set("active_id", `discuss.channel_${channelId}`);
    if (joinCall) {
        url.searchParams.set("call", "accept");
    }
    await sw.clients.openWindow(url.toString());
}

sw.addEventListener(
    "notificationclick",
    /** @param {NotificationEvent} event */ (event) => {
        event.notification.close();
        if (event.notification.data) {
            const { action, model, res_id } = event.notification.data;
            if (model === "discuss.channel") {
                if (event.action === PUSH_NOTIFICATION_ACTION.DECLINE) {
                    event.waitUntil(
                        fetch("/mail/rtc/channel/leave_call", {
                            headers: { "Content-type": "application/json" },
                            body: JSON.stringify({
                                id: 1,
                                jsonrpc: "2.0",
                                method: "call",
                                params: { channel_id: res_id },
                            }),
                            method: "POST",
                            mode: "cors",
                            credentials: "include",
                        }),
                    );
                    return;
                }
                event.waitUntil(
                    openDiscussChannel(res_id, {
                        action,
                        joinCall: event.action === PUSH_NOTIFICATION_ACTION.ACCEPT,
                    }),
                );
            } else if (model) {
                event.waitUntil(
                    clients.openWindow(notificationTargetPath(model, res_id)),
                );
            }
        }
    },
);
sw.addEventListener(
    "push",
    /** @param {PushEvent} event */ (event) => {
        let notification;
        try {
            notification = event.data?.json();
        } catch {
            notification = undefined;
        }
        const plan = planPushNotification(notification, {
            isAndroid: navigator.userAgent.includes("Android"),
        });
        switch (plan.type) {
            case "generic":
                event.waitUntil(sw.registration.showNotification("Odoo"));
                return;
            case "show":
                event.waitUntil(
                    sw.registration.showNotification(plan.title, plan.options || {}),
                );
                return;
            case "ignore":
                return;
            case "cancel":
                event.waitUntil(
                    sw.registration
                        .getNotifications({ tag: plan.tag })
                        .then((notifications) => {
                            for (const toCancel of notifications) {
                                toCancel.close();
                            }
                        }),
                );
                return;
            case "handshake":
                event.waitUntil(handlePushEvent(notification));
                return;
        }
    },
);

/** @type {Map<string, Function>} */
sw.handlePushEventMessageFns = new Map();

sw.addEventListener(
    "message",
    /** @param {ExtendableMessageEvent} ev */ ({ data }) => {
        const { type, payload } = data;
        if (type === "notification-display-response") {
            const fn = sw.handlePushEventMessageFns.get(payload.correlationId);
            if (fn) {
                sw.handlePushEventMessageFns.delete(payload.correlationId);
                fn();
            }
        }
    },
);

let unreadUpdatePromise = Promise.resolve();
function incrementUnread() {
    unreadUpdatePromise = unreadUpdatePromise.then(async () => {
        try {
            const oldCounter = (await get("unread", unread_store)) ?? 0;
            const newCounter = oldCounter + 1;
            await set("unread", newCounter, unread_store);
            navigator.setAppBadge?.(newCounter);
        } catch {}
    });
    return unreadUpdatePromise;
}

/**
 * @param {{options?: {data?: {model: string, res_id: number}}}} notification
 * @returns {Promise<void>}
 */
async function handlePushEvent(notification) {
    const { model, res_id } = notification.options?.data || {};
    const correlationId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let timeoutId;
    return new Promise((resolve) => {
        sw.handlePushEventMessageFns.set(correlationId, () => {
            clearTimeout(timeoutId);
            resolve();
        });
        sw.clients
            .matchAll({ includeUncontrolled: true, type: "window" })
            .then((clients) => {
                clients.forEach((client) =>
                    client.postMessage({
                        type: "notification-display-request",
                        payload: { correlationId, model, res_id },
                    }),
                );
            });
        timeoutId = setTimeout(async () => {
            sw.handlePushEventMessageFns.delete(correlationId);
            await incrementUnread();
            sw.clients
                .matchAll({ includeUncontrolled: true, type: "window" })
                .then((clients) => {
                    clients.forEach((client) =>
                        client.postMessage({
                            type: "notification-displayed",
                            payload: { model, res_id },
                        }),
                    );
                });
            resolve(
                sw.registration.showNotification(
                    notification.title,
                    notification.options,
                ),
            );
        }, 500);
    });
}
sw.addEventListener(
    "pushsubscriptionchange",
    /** @param {PushSubscriptionChangeEvent} event */ (event) => {
        if (!event.oldSubscription) {
            return;
        }
        event.waitUntil(resubscribePushDevice(event));
    },
);

/** @param {PushSubscriptionChangeEvent} event */
async function resubscribePushDevice(event) {
    const subscription = await sw.registration.pushManager.subscribe(
        event.oldSubscription.options,
    );
    const applicationServerKey =
        event.oldSubscription.options?.applicationServerKey ||
        subscription.options?.applicationServerKey;
    await fetch("/web/dataset/call_kw/mail.push.device/register_devices", {
        headers: {
            "Content-type": "application/json",
        },
        body: JSON.stringify({
            id: 1,
            jsonrpc: "2.0",
            method: "call",
            params: {
                model: "mail.push.device",
                method: "register_devices",
                args: [],
                kwargs: {
                    ...subscription.toJSON(),
                    previousEndpoint: event.oldSubscription.endpoint,
                    ...(applicationServerKey
                        ? {
                              vapid_public_key:
                                  arrayBufferToBase64Url(applicationServerKey),
                          }
                        : {}),
                },
                context: {},
            },
        }),
        method: "POST",
        mode: "cors",
        credentials: "include",
    });
}
sw.addEventListener(
    "message",
    /** @param {ExtendableMessageEvent} ev */ async ({ data, source }) => {
        switch (data.name) {
            case MESSAGE_TYPE.POST_RTC_LOGS: {
                const { logs, download } = data;
                try {
                    const data = await storeLogs(logs, { download });
                    if (download) {
                        source.postMessage({
                            action: "POST_RTC_LOGS",
                            data,
                        });
                    }
                } catch (error) {
                    console.error("Error storing log:", error);
                }
                break;
            }
        }
    },
);
