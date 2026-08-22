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
 * Recovery from a lost connection: one sticky notification, one back-off poll
 * of a cheap route, and one "you are back online" when it answers.
 *
 * It is a service and not a closure inside the error handler because it owns
 * three things that outlive a single error -- a timer, a notification handle,
 * and a "give up, we are shutting down" flag -- and something has to be able to
 * stop them. It used to keep exactly those three in a module-level WeakMap
 * keyed by env, created lazily by the handler rather than by the service. Two
 * consequences followed. The handler and the service talked through a side
 * channel instead of through `env.services`. And `destroy()` set a `destroyed`
 * flag on that shared entry which nothing ever cleared, so a service torn down
 * and started again on the same env came back **silently broken**: measured, a
 * second start still reported the error as handled -- `preventDefault()` called,
 * rejection swallowed -- while showing the user nothing and scheduling no retry.
 * State that outlives the thing whose lifecycle governs it can only fail that
 * way, so it now lives in the closure `destroy()` closes over.
 *
 * It owns the state, not the telling. Announcing to the user is the caller's,
 * passed to `reportLost` -- core cannot reach the notification service without
 * inverting the layers, and the caller that reports a lost connection is by
 * construction one that can speak to the user. `openSessionExpired` has taken
 * its dialog the same way since before this service existed.
 */

/**
 * @typedef {object} ConnectionAnnouncer
 * @property {() => (() => void)} lost shows "connection lost"; returns its remover
 * @property {() => void} restored shows "you are back online"
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
             * @returns {boolean} whether a session-expired dialog is already up,
             * so the caller does not stack a second one.
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
             * Announce the connection as lost and start polling. Idempotent:
             * while a notification is up, further losses are absorbed.
             *
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
