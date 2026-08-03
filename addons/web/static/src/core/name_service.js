// @ts-check
/** @odoo-module native */

/** @module @web/core/name_service */

import { AppEvent, UserEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { userBus } from "@web/core/user";
import { unique, zip } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
export const ERROR_INACCESSIBLE_OR_MISSING = Symbol(
    "INACCESSIBLE OR MISSING RECORD ID",
);

export const NAME_CACHE_LIMIT = 20000;

/**
 * @param {string} resModel
 * @param {number|string} resId
 * @returns {string}
 */
function cacheKey(resModel, resId) {
    return `${resModel}\x00${resId}`;
}

/**
 * @param {any} val
 * @returns {boolean}
 */
function isId(val) {
    return Number.isInteger(val) && val >= 1;
}

/**
 * @typedef {Record<string, (string|ERROR_INACCESSIBLE_OR_MISSING)>} DisplayNames
 */

/**
 * The `name` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * `clearCache` is subscribed to two buses, so it is registered through a stored
 * wrapper rather than as a bare method reference: `removeEventListener` needs
 * the same function object it was given, while the behaviour itself must
 * resolve through the prototype for a patch to be reached.
 */
export class NameService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     */
    constructor(env, { orm }) {
        this.env = env;
        this.orm = orm;
        /** @type {Map<string, import("@web/core/utils/concurrency").Deferred>} */
        this.cache = new Map();
        /**
         * @type {Record<string, { resId: number, deferred: import("@web/core/utils/concurrency").Deferred }[]>}
         */
        this.batches = Object.create(null);

        this._clearCache = () => this.clearCache();
        env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, this._clearCache);
        userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, this._clearCache);
    }

    /**
     * @param {string} key
     * @returns {import("@web/core/utils/concurrency").Deferred | undefined}
     */
    cacheGet(key) {
        const deferred = this.cache.get(key);
        if (deferred !== undefined) {
            this.cache.delete(key);
            this.cache.set(key, deferred);
        }
        return deferred;
    }

    /**
     * @param {string} key
     * @param {import("@web/core/utils/concurrency").Deferred} deferred
     */
    cacheSet(key, deferred) {
        this.cache.delete(key);
        this.cache.set(key, deferred);
        if (this.cache.size > NAME_CACHE_LIMIT) {
            this.cache.delete(this.cache.keys().next().value);
        }
    }

    clearCache() {
        this.cache = new Map();
    }

    /**
     * @param {string} resModel
     * @param {DisplayNames} displayNames
     */
    addDisplayNames(resModel, displayNames) {
        for (const resId of Object.keys(displayNames)) {
            const key = cacheKey(resModel, resId);
            this.cache.get(key)?.resolve(displayNames[resId]);
            const entry = new Deferred();
            entry.resolve(displayNames[resId]);
            this.cacheSet(key, entry);
        }
    }

    /**
     * @param {string} resModel
     * @param {number} resId
     * @param {import("@web/core/utils/concurrency").Deferred} deferred
     */
    evict(resModel, resId, deferred) {
        const key = cacheKey(resModel, resId);
        if (this.cache.get(key) === deferred) {
            this.cache.delete(key);
        }
    }

    /**
     * @param {string} resModel
     * @param {number[]} resIds
     * @returns {Promise<DisplayNames>}
     */
    async loadDisplayNames(resModel, resIds) {
        const proms = [];
        /** @type {{ resId: number, deferred: import("@web/core/utils/concurrency").Deferred }[]} */
        const entriesToFetch = [];
        const uniqueIds = unique(resIds);
        for (const resId of uniqueIds) {
            if (!isId(resId)) {
                throw new Error(`Invalid ID: ${resId}`);
            }
        }
        for (const resId of uniqueIds) {
            const key = cacheKey(resModel, resId);
            let deferred = this.cacheGet(key);
            if (deferred === undefined) {
                deferred = new Deferred();
                this.cacheSet(key, deferred);
                entriesToFetch.push({ resId, deferred });
            }
            proms.push(deferred);
        }
        if (entriesToFetch.length) {
            if (this.batches[resModel]) {
                this.batches[resModel].push(...entriesToFetch);
            } else {
                this.batches[resModel] = entriesToFetch;
                await Promise.resolve();
                const batch = this.batches[resModel];
                delete this.batches[resModel];
                const idsInBatch = unique(batch.map((entry) => entry.resId));

                const specification = { display_name: {} };
                this.orm.silent
                    .webSearchRead(resModel, [["id", "in", idsInBatch]], {
                        specification,
                        context: { active_test: false },
                    })
                    .then(
                        (
                            /** @type {{ records: { id: number, display_name: string }[] }} */ {
                                records,
                            },
                        ) => {
                            const displayNames = Object.fromEntries(
                                records.map((rec) => [rec.id, rec.display_name]),
                            );
                            for (const { resId, deferred } of batch) {
                                if (resId in displayNames) {
                                    deferred.resolve(displayNames[resId]);
                                } else {
                                    deferred.resolve(ERROR_INACCESSIBLE_OR_MISSING);
                                }
                            }
                        },
                    )
                    .catch((/** @type {unknown} */ error) => {
                        for (const { resId, deferred } of batch) {
                            deferred.reject(error);
                            this.evict(resModel, resId, deferred);
                        }
                    });
            }
        }
        const names = await Promise.all(proms);
        const namesById = Object.fromEntries(zip(uniqueIds, names));
        return Object.fromEntries(resIds.map((resId) => [resId, namesById[resId]]));
    }

    destroy() {
        this.env.bus.removeEventListener(
            AppEvent.ACTION_MANAGER_UPDATE,
            this._clearCache,
        );
        userBus.removeEventListener(
            UserEvent.ACTIVE_COMPANIES_CHANGED,
            this._clearCache,
        );
    }
}

export const nameService = {
    dependencies: ["orm"],
    async: ["loadDisplayNames"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     * @returns {NameService}
     */
    start(env, services) {
        return new NameService(env, services);
    },
};

registry.category("services").add("name", nameService);
