// @ts-check
/** @odoo-module native */

/** @module @web/webclient/session_service - Service that lazy-loads additional session info after the web client is ready */

import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { deepCopy } from "@web/core/utils/collections/objects";
export const lazySession = {
    dependencies: ["orm"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/services/orm_service").ORM }} services
     * @returns {{ getValue: (key: string, callback?: (value: any) => void) => Promise<any> }}
     */
    start(env, { orm }) {
        /** @type {((value?: any) => void) | undefined} */
        let resolveWebClientReady;
        /** @type {Promise<Record<string, any>> | undefined} */
        let lazyConfigPromise;
        /** @returns {Promise<Record<string, any>>} */
        const fetchServerData = async () => {
            await webClientReadyPromise;
            return orm.call("ir.http", "lazy_session_info");
        };
        const webClientReadyPromise = new Promise((r) => (resolveWebClientReady = r));
        env.bus.addEventListener(AppEvent.WEB_CLIENT_READY, resolveWebClientReady, {
            once: true,
        });
        return {
            /**
             * Fetch a lazy session value.
             *
             * Returns a Promise resolving to the value (rejecting if the
             * underlying fetch failed) so callers can ``await`` it and retry a
             * transient failure — the previous callback-only form silently
             * swallowed failures, leaving the sole consumer (profiling) stuck
             * on defaults for the whole page after one hiccup. The optional
             * ``callback`` is retained for back-compat (enterprise iot); it is
             * invoked with the value on success and skipped on failure.
             *
             * @param {string} key - Session info key to retrieve
             * @param {(value: any) => void} [callback] - Called with the value on success
             * @returns {Promise<any>} the value (rejects on fetch failure)
             */
            getValue(key, callback) {
                if (!lazyConfigPromise) {
                    const promise = fetchServerData();
                    lazyConfigPromise = promise;
                    promise.catch((error) => {
                        // Don't cache a failed fetch forever: let the next
                        // getValue call retry (unless a retry already started).
                        if (lazyConfigPromise === promise) {
                            lazyConfigPromise = null;
                        }
                        console.warn("Lazy session-info fetch failed", error);
                    });
                }
                const valuePromise = lazyConfigPromise.then((config) =>
                    deepCopy(config[key]),
                );
                if (callback) {
                    // Back-compat: fire the callback on success only. The `() =>
                    // {}` reject arm keeps this branch from surfacing an
                    // unhandled rejection when the caller ignores the promise.
                    valuePromise.then(callback, () => {});
                } else {
                    // Promise-form callers own error handling (await/catch);
                    // attach a no-op so an ignored promise never leaks an
                    // unhandled rejection, without stopping the caller's own
                    // catch from seeing it.
                    valuePromise.catch(() => {});
                }
                return valuePromise;
            },
        };
    },
};

registry.category("services").add("lazy_session", lazySession);
