// @ts-check
/** @odoo-module native */

/** @module @web/services/name_service - Batched and cached display_name lookups across arbitrary models */

/** Sentinel value indicating a record ID that is inaccessible or does not exist. */

import { AppEvent, UserEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { unique, zip } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
import { userBus } from "@web/services/user";
export const ERROR_INACCESSIBLE_OR_MISSING = Symbol(
    "INACCESSIBLE OR MISSING RECORD ID",
);

/**
 * Max number of display-name entries kept across ALL models before the
 * least-recently-used one is evicted. The cache is otherwise only cleared
 * wholesale on the two visibility events, so without a cap a long-lived action
 * that scrolls large lists / m2o autocompletes accumulates one entry per unique
 * id for the whole time it is displayed. Eviction only ever forces a re-fetch
 * (never serves stale data), so it is safe alongside the miss-cache invariant.
 */
export const NAME_CACHE_LIMIT = 20000;

/**
 * Flat cache key for a (model, id) pair. ``\x00`` cannot appear in a model
 * technical name, and template coercion makes numeric and string ids collide on
 * the same key (as the previous nested plain-object cache did).
 * @param {string} resModel
 * @param {number|string} resId
 * @returns {string}
 */
function cacheKey(resModel, resId) {
    return `${resModel}\x00${resId}`;
}

/**
 * Check whether a value is a valid Odoo record ID (positive integer).
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
 * Service that batches and caches `display_name` lookups for arbitrary models.
 * Requests within the same microtask are automatically merged into a single RPC.
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
     * }} ``destroy`` detaches the ``env.bus`` and ``userBus`` cache-clear
     *   listeners; the service registry calls it on env teardown.
     */
    start(env, { orm }) {
        /** @type {Map<string, import("@web/core/utils/concurrency").Deferred>} */
        let cache = new Map();

        /**
         * LRU read: return the entry (if any), moving it to the warm end.
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
         * LRU write: insert/refresh ``key`` at the warm end, evicting the
         * coldest entry once the cache exceeds ``NAME_CACHE_LIMIT``. Eviction
         * only drops an entry, forcing a later re-fetch — it never serves stale
         * data, so the miss-cache invariant below is unaffected.
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
         * Pending fetches per model, each entry owning its Deferred (not read
         * through `cache`): `clearCache` may swap the cache mid-flight, and this
         * decoupling ensures post-swap joiners are still settled by the
         * in-flight batch instead of orphaned.
         * @type {Record<string, { resId: number, deferred: import("@web/core/utils/concurrency").Deferred }[]>}
         */
        const batches = Object.create(null);

        /**
         * Invalidate the display name cache (on action manager updates).
         * In-flight batches are untouched: their Deferreds settle pre-clear
         * callers, while the swapped cache forces post-clear callers to re-fetch.
         */
        function clearCache() {
            cache = new Map();
        }

        env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, clearCache);
        userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, clearCache);

        /**
         * @param {string} resModel valid resModel name
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
         * @param {string} resModel valid resModel name
         * @param {number[]} resIds valid ids
         * @returns {Promise<DisplayNames>}
         */
        /**
         * Evict an entry whose fetch FAILED, so a later lookup re-fetches.
         *
         * A record the server did not return is NOT evicted: that negative
         * result is cached deliberately, and stays valid until one of the two
         * visibility events clears the whole cache (see the service's INVARIANT
         * — an inaccessible/missing id must not re-fetch on every render).
         *
         * Only evict if the current cache still holds this very Deferred: after
         * a `clearCache` the slot may be absent or already repopulated by a
         * newer epoch's fetch.
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
