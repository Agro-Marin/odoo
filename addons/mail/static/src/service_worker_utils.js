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
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

/**
 * @param {{title?: string, options?: Object}} [notification]
 * @param {{isAndroid?: boolean}} [env]
 * @returns {{type: string, title?: string, options?: Object, tag?: string}}
 */
export function planPushNotification(notification, { isAndroid = false } = {}) {
    const dataType = notification?.options?.data?.type;
    if (dataType === PUSH_NOTIFICATION_TYPE.CANCEL) {
        const tag = notification.options?.tag;
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
    return { type: "handshake" };
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
