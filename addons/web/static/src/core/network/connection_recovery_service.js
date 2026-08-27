// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

const INITIAL_DELAY = 2000;
const MAX_DELAY = 60_000;

/**
 * @typedef {object} ConnectionAnnouncer
 * @property {() => (() => void)} lost
 * @property {() => void} restored
 */

class ConnectionRecoveryService {
    constructor() {
        /** @type {(() => void) | null} */
        this.notifRemove = null;
        /** @type {ConnectionAnnouncer | null} */
        this.announcer = null;
        /** @type {any} */
        this.retryTimer = null;
        this.sessionExpiredOpen = false;
        this.destroyed = false;
    }

    get isDestroyed() {
        return this.destroyed;
    }

    /**
     * @returns {boolean}
     */
    get isSessionExpiredOpen() {
        return this.sessionExpiredOpen;
    }

    /** @param {() => void} open */
    openSessionExpired(open) {
        if (this.sessionExpiredOpen) {
            return;
        }
        this.sessionExpiredOpen = true;
        open();
    }

    closeSessionExpired() {
        this.sessionExpiredOpen = false;
    }

    /**
     * @param {ConnectionAnnouncer} announce
     */
    reportLost(announce) {
        if (this.notifRemove) {
            return;
        }
        this.announcer = announce;
        this.notifRemove = announce.lost();
        this.poll(INITIAL_DELAY);
    }

    clearNotification() {
        this.notifRemove?.();
        this.notifRemove = null;
    }

    /** @param {number} delay */
    poll(delay) {
        this.retryTimer = browser.setTimeout(() => {
            this.retryTimer = null;
            if (this.destroyed) {
                return;
            }
            rpc("/web/webclient/version_info", {}, { silent: true }).then(
                () => {
                    if (this.destroyed) {
                        return;
                    }
                    this.clearNotification();
                    this.announcer?.restored();
                },
                () => {
                    if (this.destroyed) {
                        return;
                    }
                    this.poll(Math.min(delay * 1.5 + 500 * Math.random(), MAX_DELAY));
                },
            );
        }, delay);
    }

    destroy() {
        this.destroyed = true;
        if (this.retryTimer !== null) {
            browser.clearTimeout(this.retryTimer);
            this.retryTimer = null;
        }
        this.clearNotification();
    }
}

export const connectionRecoveryService = {
    /**
     * @param {import("@web/env").OdooEnv} _
     * @returns {ConnectionRecoveryService}
     */
    start(_) {
        return new ConnectionRecoveryService();
    },
};

registry.category("services").add("connection_recovery", connectionRecoveryService);
