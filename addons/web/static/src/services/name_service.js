// @ts-check
/** @odoo-module native */

/** @module @web/services/name_service - Batched and cached display_name lookups across arbitrary models */

/** Sentinel value indicating a record ID that is inaccessible or does not exist. */

import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { unique, zip } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
export const ERROR_INACCESSIBLE_OR_MISSING = Symbol(
    "INACCESSIBLE OR MISSING RECORD ID",
);

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
        /** @type {Record<string, Record<string, import("@web/core/utils/concurrency").Deferred>>} */
        let cache = Object.create(null);
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
            cache = Object.create(null);
        }

        env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, clearCache);

        /**
         * Get or create the id→Deferred mapping for a model.
         * @param {string} resModel
         * @returns {Record<string, import("@web/core/utils/concurrency").Deferred>}
         */
        function getMapping(resModel) {
            if (!cache[resModel]) {
                cache[resModel] = Object.create(null);
            }
            return cache[resModel];
        }

        /**
         * @param {string} resModel valid resModel name
         * @param {DisplayNames} displayNames
         */
        function addDisplayNames(resModel, displayNames) {
            const mapping = getMapping(resModel);
            for (const resId of Object.keys(displayNames)) {
                // Reuse an existing (possibly in-flight) Deferred instead of
                // replacing it — a concurrent loadDisplayNames caller may be
                // awaiting it; resolving is idempotent so this is safe.
                if (!(resId in mapping)) {
                    mapping[resId] = new Deferred();
                }
                mapping[resId].resolve(displayNames[resId]);
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
            if (cache[resModel]?.[resId] === deferred) {
                delete cache[resModel][resId];
            }
        }

        async function loadDisplayNames(resModel, resIds) {
            const mapping = getMapping(resModel);
            const proms = [];
            /** @type {{ resId: number, deferred: import("@web/core/utils/concurrency").Deferred }[]} */
            const entriesToFetch = [];
            const uniqueIds = unique(resIds);
            // Validate BEFORE mutating the shared mapping: throwing mid-loop
            // would leave pending Deferreds nobody ever resolves — every
            // later load of those valid ids would join an orphan and hang.
            for (const resId of uniqueIds) {
                if (!isId(resId)) {
                    throw new Error(`Invalid ID: ${resId}`);
                }
            }
            for (const resId of uniqueIds) {
                if (!(resId in mapping)) {
                    mapping[resId] = new Deferred();
                    entriesToFetch.push({ resId, deferred: mapping[resId] });
                }
                proms.push(mapping[resId]);
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
                                        // Missing/inaccessible isn't durable: resolve
                                        // pending callers but evict the entry so a later
                                        // lookup re-fetches — the record may become
                                        // readable after an ACL/company change that
                                        // doesn't fire ACTION_MANAGER:UPDATE (e.g.
                                        // recoverFromSaveError with reload:false).
                                        deferred.resolve(ERROR_INACCESSIBLE_OR_MISSING);
                                        evict(resModel, resId, deferred);
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

        return { addDisplayNames, clearCache, loadDisplayNames };
    },
};

registry.category("services").add("name", nameService);
