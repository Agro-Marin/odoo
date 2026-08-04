/** @odoo-module native */
import { htmlToTextContentInline } from "@mail/utils/common/format";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
const PREVIEW_MSG_MAX_SIZE = 350; // optimal for native English speakers

export class OutOfFocusService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.setup(env, services);
    }

    setup(env, services) {
        this.env = env;
        this.audio = undefined;
        this.multiTab = services.multi_tab;
        this.notificationService = services.notification;
        this.soundEffectService = services["mail.sound_effects"];
        /** @type {import("models").Store} */
        this.store = services["mail.store"];
        this.closeFuncs = [];
    }

    async notify(message, thread) {
        // "discuss.channel" literal: push-payload model names handled by the
        // service worker, not a Thread-record conditional.
        const modelsHandleByPush = ["mail.thread", "discuss.channel"];
        if (
            modelsHandleByPush.includes(message.thread?.model) &&
            (await this.hasServiceWorkInstalledAndPushSubscriptionActive())
        ) {
            return;
        }
        const author = message.author;
        let notificationTitle;
        let icon = "/mail/static/src/img/odoobot_transparent.png";
        if (!author) {
            notificationTitle = _t("New message");
        } else {
            icon = author.avatarUrl;
            notificationTitle =
                message.thread?.outOfFocusNotificationTitle(message) ??
                message.authorName;
        }
        const notificationContent = htmlToTextContentInline(
            message.previewText,
        ).substring(0, PREVIEW_MSG_MAX_SIZE);
        await this.sendNotification({
            message: notificationContent,
            sound: Boolean(message.thread?.isChannelKind),
            title: notificationTitle,
            type: "info",
            icon,
        });
    }

    async hasServiceWorkInstalledAndPushSubscriptionActive() {
        const registration = await browser.navigator.serviceWorker?.getRegistration();
        if (registration) {
            const pushManager = await registration.pushManager;
            if (pushManager) {
                const subscription = await pushManager.getSubscription();
                return !!subscription;
            }
        }
        return false;
    }

    /**
     * Send a notification, preferably a native one. If native
     * notifications are disable or unavailable on the current
     * platform, fallback on the notification service.
     *
     * @param {Object} param0
     * @param {string} [param0.message] The body of the
     * notification.
     * @param {boolean} [param0.sound=true] Whether to also play a sound.
     * @param {string} [param0.title] The title of the notification.
     * @param {string} [param0.type] The type to be passed to the notification
     * service when native notifications can't be sent.
     * @param {string} [param0.icon] The icon to be displayed in the
     * notification.
     */
    async sendNotification({ message, sound = true, title, type, icon }) {
        if (!this.canSendNativeNotification || !(await this.multiTab.isOnMainTab())) {
            if (sound) {
                this._playSound();
            }
            return;
        }
        try {
            this.sendNativeNotification(title, message, icon, { sound });
        } catch (error) {
            // Notification without Serviceworker in Chrome Android doesn't works anymore
            // So we fallback to the notification service in this case
            // https://bugs.chromium.org/p/chromium/issues/detail?id=481856
            // String(): a thrown non-Error (or an Error without a message) made
            // this branch throw a TypeError of its own, losing the original
            if (String(error?.message ?? "").includes("ServiceWorkerRegistration")) {
                this.sendOdooNotification(message, { sound, title, type });
            } else {
                throw error;
            }
        }
    }

    /**
     * @param {string} message
     * @param {Object} options
     */
    async sendOdooNotification(message, { sound, ...options } = {}) {
        // destructured rather than `delete options.sound`: mutating the
        // caller's object to strip a key it passed in is a trap for any future
        // call site that reuses its options literal
        this.closeFuncs.push(this.notificationService.add(message, options));
        if (this.closeFuncs.length > 3) {
            this.closeFuncs.shift()();
        }
        if (sound) {
            this._playSound();
        }
    }

    /**
     * @param {string} title
     * @param {string} message
     */
    sendNativeNotification(title, message, icon, { sound = true } = {}) {
        const notification = new browser.Notification(title, {
            body: message,
            icon,
        });
        notification.addEventListener("click", ({ target: notification }) => {
            window.focus();
            notification.close();
        });
        if (sound) {
            this._playSound();
        }
    }

    async _playSound() {
        if (
            this.canPlayAudio &&
            this.store.settings.messageSound &&
            (await this.multiTab.isOnMainTab())
        ) {
            this.soundEffectService.play("new-message");
        }
    }

    get canPlayAudio() {
        return typeof Audio !== "undefined";
    }

    get canSendNativeNotification() {
        // `browser.Notification`, not the raw global: it is the seam the rest
        // of the module already reads permissions through (webclient.js,
        // notification_permission_service.js), and the one tests patch. Going
        // straight to `window` made this service the only place that ignored a
        // patched permission and constructed a real OS notification.
        return Boolean(
            browser.Notification && browser.Notification.permission === "granted",
        );
    }
}

export const outOfFocusService = {
    dependencies: ["multi_tab", "notification", "mail.sound_effects", "mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const service = new OutOfFocusService(env, services);
        return service;
    },
};

registry.category("services").add("mail.out_of_focus", outOfFocusService);
