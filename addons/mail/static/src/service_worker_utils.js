/** @odoo-module */

// Pure, side-effect-free helpers for the push service worker. They live in this
// standalone ESM module so they can be unit-tested under hoot (see
// static/tests/service_worker_utils.test.js) instead of only through a live
// ServiceWorkerGlobalScope. The service worker is served as a *classic* worker
// (raw concatenated text — see mail/controllers/webmanifest.py), so it cannot
// `import` at runtime: the controller inlines this file with the `export`
// keyword stripped, ahead of service_worker.js, which then calls these as
// plain globals.

export const PUSH_NOTIFICATION_TYPE = {
    CALL: "CALL",
    CANCEL: "CANCEL",
};
export const PUSH_NOTIFICATION_ACTION = {
    ACCEPT: "ACCEPT",
    DECLINE: "DECLINE",
};

/**
 * base64url (unpadded) encoding of the VAPID applicationServerKey, matching
 * WebClient._arrayBufferToBase64 so register_devices' _verify_vapid_public_key
 * accepts it.
 *
 * @param {ArrayBuffer|ArrayBufferView} buffer
 * @returns {string}
 */
export function arrayBufferToBase64Url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

/**
 * Decide what a push event should do, without touching any ServiceWorker API.
 * Returns a plan the `push` handler executes:
 *   - {type: "generic"}                 empty/invalid payload -> show "Odoo"
 *   - {type: "show", title, options}    a CALL notification (Android-filtered)
 *   - {type: "cancel", tag}             a CANCEL scoped to a tag
 *   - {type: "ignore"}                  a tag-less CANCEL (must NOT close all)
 *   - {type: "handshake"}               default -> client display handshake
 *
 * @param {{title?: string, options?: Object}} [notification]
 * @param {{isAndroid?: boolean}} [env]
 * @returns {{type: string, title?: string, options?: Object, tag?: string}}
 */
export function planPushNotification(notification, { isAndroid = false } = {}) {
    if (!notification?.title) {
        // Browsers may penalize a push subscription when an event shows nothing,
        // so still surface a generic notification.
        return { type: "generic" };
    }
    const dataType = notification.options?.data?.type;
    if (dataType === PUSH_NOTIFICATION_TYPE.CALL) {
        let options = notification.options || {};
        if (options.actions && isAndroid) {
            // "accept" action is disabled on mobile until
            // https://issues.chromium.org/issues/40286493 is fixed. Return a
            // fresh options object rather than mutating the caller's payload.
            options = {
                ...options,
                actions: options.actions.filter(
                    (action) => action.action !== PUSH_NOTIFICATION_ACTION.ACCEPT,
                ),
            };
        }
        return { type: "show", title: notification.title, options };
    }
    if (dataType === PUSH_NOTIFICATION_TYPE.CANCEL) {
        const tag = notification.options?.tag;
        if (!tag) {
            // getNotifications({ tag: undefined }) matches everything, so a
            // tag-less CANCEL would close every notification for this origin
            // (unrelated calls/messages included). Only act when scoped.
            return { type: "ignore" };
        }
        return { type: "cancel", tag };
    }
    return { type: "handshake" };
}

/**
 * URL a notification click should open for a generic (non-discuss) record.
 * A dotted value is a real model name; otherwise it is an "m-" shorthand.
 *
 * @param {string} model
 * @param {number|string} resId
 * @returns {string}
 */
export function notificationTargetPath(model, resId) {
    const modelPath = model.includes(".") ? model : `m-${model}`;
    return `/odoo/${modelPath}/${resId}`;
}
