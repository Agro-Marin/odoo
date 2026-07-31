// @ts-check
/** @odoo-module native */

/** @module @web/services/name_service */

import { AppEvent, UserEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { unique, zip } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
import { userBus } from "@web/services/user";
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

export const nameService = {
    dependencies: ["orm"],
    async: ["loadDisplayNames"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     * @returns {{
     *   addDisplayNames: Function,
     *   clearCache: Function,
     *   loadDisplayNames: Function,
     *   destroy: () => void,
     * }}
     */
    start(env, { orm }) {
        /** @type {Map<string, import("@web/core/utils/concurrency").Deferred>} */
        let cache = new Map();

        /**
         * @param {string} key
         * @returns {import("@web/core/utils/concurrency").Deferred | undefined}
         */
        function cacheGet(key) {
            const deferred = cache.get(key);
            if (deferred !== undefined) {
                cache.delete(key);
                cache.set(key, deferred);
            }
            return deferred;
        }

        /**
         * @param {string} key
         * @param {import("@web/core/utils/concurrency").Deferred} deferred
         */
        function cacheSet(key, deferred) {
            cache.delete(key);
            cache.set(key, deferred);
            if (cache.size > NAME_CACHE_LIMIT) {
                cache.delete(cache.keys().next().value);
            }
        }
        /**
         * @type {Record<string, { resId: number, deferred: import("@web/core/utils/concurrency").Deferred }[]>}
         */
        const batches = Object.create(null);

        function clearCache() {
            cache = new Map();
        }

        env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, clearCache);
        userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, clearCache);

        /**
         * @param {string} resModel
         * @param {DisplayNames} displayNames
         */
        function addDisplayNames(resModel, displayNames) {
            for (const resId of Object.keys(displayNames)) {
                const key = cacheKey(resModel, resId);
                cache.get(key)?.resolve(displayNames[resId]);
                const entry = new Deferred();
                entry.resolve(displayNames[resId]);
                cacheSet(key, entry);
            }
        }

        /**
         * @param {string} resModel
         * @param {number} resId
         * @param {import("@web/core/utils/concurrency").Deferred} deferred
         */
        function evict(resModel, resId, deferred) {
            const key = cacheKey(resModel, resId);
            if (cache.get(key) === deferred) {
                cache.delete(key);
            }
        }

        /**
         * @param {string} resModel
         * @param {number[]} resIds
         * @returns {Promise<DisplayNames>}
         */
        async function loadDisplayNames(resModel, resIds) {
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
                let deferred = cacheGet(key);
                if (deferred === undefined) {
                    deferred = new Deferred();
                    cacheSet(key, deferred);
                    entriesToFetch.push({ resId, deferred });
                }
                proms.push(deferred);
            }
            if (entriesToFetch.length) {
                if (batches[resModel]) {
                    batches[resModel].push(...entriesToFetch);
                } else {
                    batches[resModel] = entriesToFetch;
                    await Promise.resolve();
                    const batch = batches[resModel];
                    delete batches[resModel];
                    const idsInBatch = unique(batch.map((entry) => entry.resId));

                    const specification = { display_name: {} };
                    orm.silent
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
                                evict(resModel, resId, deferred);
                            }
                        });
                }
            }
            const names = await Promise.all(proms);
            const namesById = Object.fromEntries(zip(uniqueIds, names));
            return Object.fromEntries(resIds.map((resId) => [resId, namesById[resId]]));
        }

        return {
            addDisplayNames,
            clearCache,
            loadDisplayNames,
            destroy() {
                env.bus.removeEventListener(AppEvent.ACTION_MANAGER_UPDATE, clearCache);
                userBus.removeEventListener(
                    UserEvent.ACTIVE_COMPANIES_CHANGED,
                    clearCache,
                );
            },
        };
    },
};

registry.category("services").add("name", nameService);
