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
     * @returns {{ getValue: (key: string, callback: (value: any) => void) => void }}
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
             * Fetch a lazy session value and pass it to the callback.
             * @param {string} key - Session info key to retrieve
             * @param {(value: any) => void} callback - Called with the value once fetched
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
                lazyConfigPromise.then(
                    (config) => callback(deepCopy(config[key])),
                    () => {
                        // Fetch failed: the callback is simply never called
                        // (handled above so the rejection isn't unhandled).
                    },
                );
            },
        };
    },
};

registry.category("services").add("lazy_session", lazySession);
