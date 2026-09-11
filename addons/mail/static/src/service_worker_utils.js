// @ts-check
/** @odoo-module */

export const PUSH_NOTIFICATION_TYPE = {
    CALL: "CALL",
    CANCEL: "CANCEL",
};
export const PUSH_NOTIFICATION_ACTION = {
    ACCEPT: "ACCEPT",
    DECLINE: "DECLINE",
};

/**
 * @param {ArrayBuffer|ArrayBufferView} buffer
 * @returns {string}
 */
export function arrayBufferToBase64Url(buffer) {
    const bytes = ArrayBuffer.isView(buffer)
        ? new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength)
        : new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

/**
 * @typedef {Omit<NotificationOptions, "data"> & {
 * data?: {type?: string, model?: string, res_id?: number};
 * actions?: {action: string, title: string, icon?: string}[];
 * }} PushNotificationOptions
 * @typedef {{title?: string, options?: PushNotificationOptions}} PushNotification
 * @typedef {{type: "generic" | "ignore"} |
 * {type: "cancel", tag: string} |
 * {type: "show", title: string, options: PushNotificationOptions} |
 * {type: "handshake", notification: PushNotification & {title: string}}} PushNotificationPlan
 */

/**
 * @param {PushNotification} [notification]
 * @param {{isAndroid?: boolean}} [env]
 * @returns {PushNotificationPlan}
 */
export function planPushNotification(notification, { isAndroid = false } = {}) {
    const dataType = notification?.options?.data?.type;
    if (dataType === PUSH_NOTIFICATION_TYPE.CANCEL) {
        const tag = notification?.options?.tag;
        if (!tag) {
            return { type: "ignore" };
        }
        return { type: "cancel", tag };
    }
    if (!notification?.title) {
        return { type: "generic" };
    }
    if (dataType === PUSH_NOTIFICATION_TYPE.CALL) {
        let options = notification.options || {};
        if (options.actions && isAndroid) {
            options = {
                ...options,
                actions: options.actions.filter(
                    (action) => action.action !== PUSH_NOTIFICATION_ACTION.ACCEPT,
                ),
            };
        }
        return { type: "show", title: notification.title, options };
    }
    return {
        type: "handshake",
        notification: { ...notification, title: notification.title },
    };
}

/**
 * @template {{id: string, url: string, focused?: boolean, visibilityState?: string}} T
 * @param {readonly T[]} clients
 * @param {Object} [options]
 * @param {{id: string}} [options.source]
 * @param {RegExp[]} [options.urlRegexes]
 * @returns {T|undefined}
 */
export function pickTargetClient(clients, { source, urlRegexes = [] } = {}) {
    /** @param {T} client */
    const getScore = (client) =>
        (client.focused ? 4 : 0) +
        (client.visibilityState === "visible" ? 2 : 0) +
        (urlRegexes.some((r) => r.test(new URL(client.url).pathname)) ? 1 : 0);
    let targetClient;
    for (const client of clients) {
        if (source && source.id === client.id) {
            continue;
        }
        if (!targetClient || getScore(client) > getScore(targetClient)) {
            targetClient = client;
        }
    }
    return targetClient;
}

/**
 * @param {string} model
 * @param {number|string} resId
 * @returns {string}
 */
export function notificationTargetPath(model, resId) {
    const modelPath = model.includes(".") ? model : `m-${model}`;
    return `/odoo/${modelPath}/${resId}`;
}
