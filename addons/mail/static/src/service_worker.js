/** @odoo-module native */
/* eslint-env serviceworker */

/* global idbKeyval */
importScripts("/mail/static/lib/idb-keyval/idb-keyval.js");

const MESSAGE_TYPE = {
    UNEXPECTED_CALL_TERMINATION: "UNEXPECTED_CALL_TERMINATION", // deprecated
    POST_RTC_LOGS: "POST_RTC_LOGS",
};
const PUSH_NOTIFICATION_TYPE = {
    CALL: "CALL",
    CANCEL: "CANCEL",
};
const PUSH_NOTIFICATION_ACTION = {
    ACCEPT: "ACCEPT",
    DECLINE: "DECLINE",
};

const { Store, set, get } = idbKeyval;
const LOG_AGE_LIMIT = 24 * 60 * 60 * 1000; // 24h

// base64url (unpadded) encoding of the VAPID applicationServerKey, matching
// WebClient._arrayBufferToBase64 so register_devices' _verify_vapid_public_key
// accepts it.
function arrayBufferToBase64Url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
let db;
let dbPromise;
const unread_store = new Store("odoo-mail-unread-db", "odoo-mail-unread-store");
let interactionSinceCleanupCount = 0;

function openDatabase() {
    // Memoize the open: openDatabase() is called from both the `activate`
    // handler and lazily from storeLogs(); without this, concurrent calls each
    // open a separate IDB connection and clobber the shared `db` global.
    dbPromise ??= new Promise((resolve, reject) => {
        const request = indexedDB.open("RtcLogsDB", 1);
        request.onupgradeneeded = function (event) {
            const db = event.target.result;
            if (!db.objectStoreNames.contains("logs")) {
                const store = db.createObjectStore("logs", {
                    keyPath: "id",
                    autoIncrement: true,
                });
                store.createIndex("timestamp", "timestamp", { unique: false });
            }
        };
        request.onsuccess = async function (event) {
            db = event.target.result;
            try {
                await cleanupLogs(db);
            } catch (error) {
                console.error("Error cleaning up logs:", error);
            }
            resolve(db);
        };
        request.onerror = function (event) {
            // allow a later retry to re-open after a failed attempt
            dbPromise = undefined;
            reject(event.target.error);
        };
    });
    return dbPromise;
}

self.addEventListener("install", () => {
    // Activate a freshly installed/updated worker without waiting for every
    // controlled tab to close, so clients.claim() below can take control of the
    // pages that are already open.
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    // clients.claim(): take control of already-open pages immediately. Without
    // it, the page that registered the worker stays uncontrolled until its next
    // navigation, so navigator.serviceWorker.controller is null there and the
    // push-dedup response (see the notification-display-request handshake)
    // cannot be routed back through it — the worker then always times out and
    // shows a duplicate notification on the focused tab.
    event.waitUntil(Promise.all([openDatabase(), self.clients.claim()]));
});

async function cleanupLogs(dataBase) {
    const cutoffTime = Date.now() - LOG_AGE_LIMIT;
    return new Promise((resolve, reject) => {
        const tx = dataBase.transaction("logs", "readwrite");
        const store = tx.objectStore("logs");
        const index = store.index("timestamp");
        const range = IDBKeyRange.upperBound(cutoffTime);
        const request = index.openCursor(range);
        request.onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
                cursor.delete();
                cursor.continue();
            }
        };
        request.onerror = (event) => reject(event.target.error);
        tx.oncomplete = () => resolve();
        tx.onerror = (event) => reject(event.target.error);
    });
}

async function storeLogs(logs, { download = false } = {}) {
    if (!db) {
        await openDatabase();
    }
    if (interactionSinceCleanupCount > 30) {
        // cleanup logs in case the service worker lives for a long time
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
            request.onerror = (event) => reject(event.target.error);
        }
        if (download) {
            const request = store.getAll();
            request.onerror = (event) => reject(event.target.error);
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
        tx.onerror = (event) => reject(event.target.error);
    });
}

/**
 * @param {number} channelId id of the mail discuss channel
 * @param {Object} param1
 * @param {string} [param1.action] odoo client action
 * @param {boolean} [param1.joinCall] whether we want to join a call on that channel
 * @param {Client | ServiceWorker | MessagePort} [source] if set, will not open the channel on the source
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
    // Prefer the client the user is looking at (focused, then visible), and
    // among equals a discuss client over any other.
    const getScore = (client) =>
        (client.focused ? 4 : 0) +
        (client.visibilityState === "visible" ? 2 : 0) +
        (discussURLRegexes.some((r) => r.test(new URL(client.url).pathname)) ? 1 : 0);
    let targetClient;
    for (const client of await self.clients.matchAll({
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
    // No client at all: open a new window on the channel.
    const url = action
        ? new URL(`/odoo/action-${action}`, location.origin)
        : new URL("/odoo/discuss", location.origin);
    url.searchParams.set("active_id", `discuss.channel_${channelId}`);
    if (joinCall) {
        url.searchParams.set("call", "accept");
    }
    await self.clients.openWindow(url.toString());
}

self.addEventListener("notificationclick", (event) => {
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
        } else {
            const modelPath = model.includes(".") ? model : `m-${model}`;
            event.waitUntil(clients.openWindow(`/odoo/${modelPath}/${res_id}`));
        }
    }
});
self.addEventListener("push", (event) => {
    let notification;
    try {
        notification = event.data?.json();
    } catch {
        notification = undefined;
    }
    if (!notification?.title) {
        // Empty or invalid payload: still show a generic notification, as
        // browsers may penalize the push subscription when a push event
        // doesn't show anything.
        event.waitUntil(self.registration.showNotification("Odoo"));
        return;
    }
    switch (notification.options?.data?.type) {
        case PUSH_NOTIFICATION_TYPE.CALL:
            if (
                notification.options.actions &&
                navigator.userAgent.includes("Android")
            ) {
                // action "accept" is disabled on mobile until: https://issues.chromium.org/issues/40286493 is fixed.
                notification.options.actions = notification.options.actions.filter(
                    (a) => a.action !== PUSH_NOTIFICATION_ACTION.ACCEPT,
                );
            }
            event.waitUntil(
                self.registration.showNotification(
                    notification.title,
                    notification.options || {},
                ),
            );
            return;
        case PUSH_NOTIFICATION_TYPE.CANCEL: {
            const tag = notification.options?.tag;
            if (!tag) {
                // getNotifications({ tag: undefined }) is "match everything", so
                // a tag-less CANCEL would close every notification for this
                // origin (unrelated calls/messages included). A CANCEL is only
                // meaningful when scoped to a tag; ignore it otherwise.
                return;
            }
            // waitUntil: without it the worker may be terminated before the
            // async getNotifications() resolves, leaving the notification up.
            event.waitUntil(
                self.registration.getNotifications({ tag }).then((notifications) => {
                    for (const toCancel of notifications) {
                        toCancel.close();
                    }
                }),
            );
            return;
        }
    }
    event.waitUntil(handlePushEvent(notification));
});

/** @type {Map<string, Function>} string is correlationId and Function is handler */
self.handlePushEventMessageFns = new Map();

self.addEventListener("message", ({ data }) => {
    const { type, payload } = data;
    if (type === "notification-display-response") {
        const fn = self.handlePushEventMessageFns.get(payload.correlationId);
        if (fn) {
            self.handlePushEventMessageFns.delete(payload.correlationId);
            fn();
        }
    }
});

// App-badge ownership contract: the "unread" key of `unread_store` is written
// by BOTH this worker (incrementUnread, for background pushes no client
// acknowledged) and the web client (store_service_patch.updateAppBadge, which
// overwrites it with the authoritative inbox counter whenever a tab is running
// and synced). The worker increments on top of the last client value; the
// client resets to its true count. Keep the store name/key in sync between the
// two files if either changes.
//
// Serialize the read-modify-write cycles on the unread counter: concurrent
// push events would otherwise read the same value and lose increments.
let unreadUpdatePromise = Promise.resolve();
function incrementUnread() {
    unreadUpdatePromise = unreadUpdatePromise.then(async () => {
        const oldCounter = (await get("unread", unread_store)) ?? 0;
        const newCounter = oldCounter + 1;
        await set("unread", newCounter, unread_store);
        navigator.setAppBadge?.(newCounter);
    });
    return unreadUpdatePromise;
}

async function handlePushEvent(notification) {
    const { model, res_id } = notification.options?.data || {};
    const correlationId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let timeoutId;
    return new Promise((resolve) => {
        // The single `message` dispatcher matches by correlationId and invokes
        // this handler only for the matching response, so no re-check is needed.
        self.handlePushEventMessageFns.set(correlationId, () => {
            clearTimeout(timeoutId);
            resolve();
        });
        self.clients
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
            // No client answered the display request: drop its handler.
            self.handlePushEventMessageFns.delete(correlationId);
            await incrementUnread();
            self.clients
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
                self.registration.showNotification(
                    notification.title,
                    notification.options,
                ),
            );
        }, 500);
    });
}
self.addEventListener("pushsubscriptionchange", (event) => {
    if (!event.oldSubscription) {
        return;
    }
    // waitUntil: without it the browser may terminate the worker between the
    // resubscription and the register_devices call, leaving the device row
    // on the dead endpoint (i.e. no more push notifications, silently).
    event.waitUntil(resubscribePushDevice(event));
});

async function resubscribePushDevice(event) {
    const subscription = await self.registration.pushManager.subscribe(
        event.oldSubscription.options,
    );
    // register_devices rejects with InvalidVapidError unless it receives the
    // current VAPID public key; the key is the applicationServerKey the old
    // subscription was created with. Without it this rotation call is dropped
    // and the device row keeps the dead endpoint.
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
                        ? { vapid_public_key: arrayBufferToBase64Url(applicationServerKey) }
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
self.addEventListener("message", async ({ data, source }) => {
    switch (data.name) {
        case MESSAGE_TYPE.UNEXPECTED_CALL_TERMINATION:
            // deprecated
            openDiscussChannel(data.channelId, { joinCall: true, source });
            break;
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
});
