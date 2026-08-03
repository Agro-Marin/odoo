// @ts-check
/** @odoo-module native */

/** @module @web/webclient/session_service */

import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { deepCopy } from "@web/core/utils/collections/objects";
/**
 * The `lazy_session` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * `_fetchServerData` is underscored: the literal published only `getValue` and
 * kept the fetch inside (hazard 6).
 */
export class LazySessionService {
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
                    // Back to unset, so the next reader starts a fresh
                    // fetch rather than re-awaiting a settled rejection.
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
     * @returns {{ getValue: (key: string, callback?: (value: any) => void) => Promise<any> }}
     */
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     * @returns {LazySessionService}
     */
    start(env, services) {
        return new LazySessionService(env, services);
    },
};

registry.category("services").add("lazy_session", lazySession);
