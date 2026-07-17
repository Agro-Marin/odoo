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
     * @returns {{ addDisplayNames: Function, clearCache: Function, loadDisplayNames: Function }}
     */
    start(env, { orm }) {
        // Flat, insertion-ordered LRU: key ``cacheKey(model, id)`` → Deferred.
        // A Map preserves insertion order, so the first key is always the
        // coldest; ``cacheGet``/``cacheSet`` re-insert on touch and evict the
        // cold end past ``NAME_CACHE_LIMIT``.
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
            cache.delete(key); // re-insert so the key moves to the warm end
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

        // INVARIANT — miss-cache correctness depends on EXACTLY these two
        // clear-cache events. A negative lookup result
        // (``ERROR_INACCESSIBLE_OR_MISSING``, resolved below) is cached like a
        // real name to stop a dead id in a saved filter re-fetching on every
        // facet recomputation. That sentinel is only safe to cache because both
        // events that can flip a record's *visibility* clear the whole cache:
        //   1. ACTION_MANAGER:UPDATE — any action/controller change.
        //   2. ACTIVE_COMPANIES_CHANGED — a company switch can make a
        //      previously-inaccessible record readable; recoverFromSaveError
        //      activates a company with reload:false, so NO
        //      ACTION_MANAGER:UPDATE fires — this listener is load-bearing, not
        //      redundant.
        // KNOWN GAP: a visibility change with NO local event — e.g. an admin
        // granting this user a res.groups membership in ANOTHER tab — leaves the
        // ERROR sentinel cached until the next action/company switch in THIS
        // tab. Accepted: the alternative (never caching misses) reintroduces the
        // per-keystroke RPC storm this trades away. If a third visibility source
        // is ever introduced, it MUST clearCache() here too.
        env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, clearCache);
        userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, clearCache);

        /**
         * @param {string} resModel valid resModel name
         * @param {DisplayNames} displayNames
         */
        function addDisplayNames(resModel, displayNames) {
            for (const resId of Object.keys(displayNames)) {
                const key = cacheKey(resModel, resId);
                // Settle any in-flight Deferred so concurrent loadDisplayNames
                // callers get the value (a no-op if it already resolved), then
                // swap in a freshly-settled entry: resolving a settled promise
                // is a no-op, so reusing it would silently drop a newer name
                // (e.g. a record renamed since its first resolution). Plain
                // ``get`` (no LRU touch) — ``cacheSet`` below does the touch.
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
         * Evict a non-durable entry (missing record or failed fetch) so a
         * later lookup re-fetches. Only evict if the current cache still
         * holds this very Deferred: after a `clearCache` the slot may be
         * absent or already repopulated by a newer epoch's fetch.
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
            // Validate BEFORE mutating the shared cache: throwing mid-loop
            // would leave pending Deferreds nobody ever resolves — every
            // later load of those valid ids would join an orphan and hang.
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
                                        // Cache the miss (do NOT evict): a dead id in a
                                        // saved filter used to re-fetch on every facet
                                        // recomputation (tree_processor rebuilds
                                        // descriptions per search interaction) — one
                                        // extra RPC per keystroke, forever. The two
                                        // visibility-changing events
                                        // (ACTION_MANAGER:UPDATE, ACTIVE_COMPANIES_CHANGED)
                                        // clear the cache, so a record that becomes
                                        // readable is still picked up.
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
            // proms/names align to unique(resIds); build id→name from that deduped
            // order then project onto resIds (may contain dups) — zipping names
            // against raw resIds would truncate/mis-assign on repeated ids.
            const names = await Promise.all(proms);
            const namesById = Object.fromEntries(zip(unique(resIds), names));
            return Object.fromEntries(resIds.map((resId) => [resId, namesById[resId]]));
        }

        return {
            addDisplayNames,
            clearCache,
            loadDisplayNames,
            destroy() {
                // ``userBus`` is a module-level singleton that outlives this env
                // (unlike ``env.bus``, which is collected with the env), so its
                // listener must be removed explicitly or every started env leaks
                // its whole display-name cache — amplified across test suites
                // that spin up many envs. Mirrors slow_rpc / result_set_cache.
                userBus.removeEventListener(
                    UserEvent.ACTIVE_COMPANIES_CHANGED,
                    clearCache,
                );
            },
        };
    },
};

registry.category("services").add("name", nameService);
