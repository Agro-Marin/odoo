// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 */

const INITIAL_DELAY = 2000;
const MAX_DELAY = 60_000;

/**
 * @typedef {object} ConnectionAnnouncer
 * @property {() => (() => void)} lost
 * @property {() => void} restored
 */
export const connectionRecoveryService = {
    /** @param {OdooEnv} env */
    start(env) {
        /** @type {(() => void) | null} */
        let notifRemove = null;
        /** @type {ConnectionAnnouncer | null} */
        let announcer = null;
        /** @type {any} */
        let retryTimer = null;
        let sessionExpiredOpen = false;
        let destroyed = false;

        function clearNotification() {
            notifRemove?.();
            notifRemove = null;
        }

        function poll(delay) {
            retryTimer = browser.setTimeout(() => {
                retryTimer = null;
                if (destroyed) {
                    return;
                }
                rpc("/web/webclient/version_info", {}, { silent: true }).then(
                    () => {
                        if (destroyed) {
                            return;
                        }
                        clearNotification();
                        announcer?.restored();
                    },
                    () => {
                        if (destroyed) {
                            return;
                        }
                        poll(Math.min(delay * 1.5 + 500 * Math.random(), MAX_DELAY));
                    },
                );
            }, delay);
        }

        return {
            get isDestroyed() {
                return destroyed;
            },
            /**
             * @returns {boolean}
             */
            get isSessionExpiredOpen() {
                return sessionExpiredOpen;
            },
            /** @param {() => void} open */
            openSessionExpired(open) {
                if (sessionExpiredOpen) {
                    return;
                }
                sessionExpiredOpen = true;
                open();
            },
            closeSessionExpired() {
                sessionExpiredOpen = false;
            },
            /**
             * @param {ConnectionAnnouncer} announce
             */
            reportLost(announce) {
                if (notifRemove) {
                    return;
                }
                announcer = announce;
                notifRemove = announce.lost();
                poll(INITIAL_DELAY);
            },
            destroy() {
                destroyed = true;
                if (retryTimer !== null) {
                    browser.clearTimeout(retryTimer);
                    retryTimer = null;
                }
                clearNotification();
            },
        };
    },
};

registry.category("services").add("connection_recovery", connectionRecoveryService);
