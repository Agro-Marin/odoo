// @ts-check
/** @odoo-module native */

/** @module @web/webclient/session_service */

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
             * @param {string} key
             * @param {(value: any) => void} [callback]
             * @returns {Promise<any>}
             */
            getValue(key, callback) {
                if (!lazyConfigPromise) {
                    const promise = fetchServerData();
                    lazyConfigPromise = promise;
                    promise.catch((error) => {
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
                    valuePromise.then(callback, () => {});
                } else {
                    valuePromise.catch(() => {});
                }
                return valuePromise;
            },
        };
    },
};

registry.category("services").add("lazy_session", lazySession);
