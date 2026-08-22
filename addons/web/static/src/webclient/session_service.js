// @ts-check
/** @odoo-module native */

import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { deepCopy } from "@web/core/utils/collections/objects";
class LazySessionService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     */
    constructor(env, { orm }) {
        this.env = env;
        this.orm = orm;
        /** @type {Promise<Record<string, any>> | undefined} */
        this.lazyConfigPromise = undefined;
        /** @type {((value?: any) => void) | undefined} */
        let resolveWebClientReady;
        this.webClientReadyPromise = new Promise((r) => (resolveWebClientReady = r));
        env.bus.addEventListener(AppEvent.WEB_CLIENT_READY, resolveWebClientReady, {
            once: true,
        });
    }

    /** @returns {Promise<Record<string, any>>} */
    async _fetchServerData() {
        await this.webClientReadyPromise;
        return this.orm.call("ir.http", "lazy_session_info");
    }

    /**
     * @param {string} key
     * @param {(value: any) => void} [callback]
     * @returns {Promise<any>}
     */
    getValue(key, callback) {
        if (!this.lazyConfigPromise) {
            const promise = this._fetchServerData();
            this.lazyConfigPromise = promise;
            promise.catch((error) => {
                if (this.lazyConfigPromise === promise) {
                    this.lazyConfigPromise = undefined;
                }
                console.warn("Lazy session-info fetch failed", error);
            });
        }
        const valuePromise = this.lazyConfigPromise.then((config) =>
            deepCopy(config[key]),
        );
        if (callback) {
            valuePromise.then(callback, () => {});
        } else {
            valuePromise.catch(() => {});
        }
        return valuePromise;
    }
}

export const lazySession = {
    dependencies: ["orm"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/core/network/orm_service").ORM }} services
     * @returns {LazySessionService}
     */
    start(env, services) {
        return new LazySessionService(env, services);
    },
};

registry.category("services").add("lazy_session", lazySession);
