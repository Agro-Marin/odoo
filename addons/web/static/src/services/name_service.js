// @ts-check
/** @odoo-module native */

/** @module @web/services/name_service - Batched and cached display_name lookups across arbitrary models */

/** Sentinel value indicating a record ID that is inaccessible or does not exist. */

import { registry } from "@web/core/registry";
import { unique, zip } from "@web/core/utils/collections/arrays";
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
        /** @type {Record<string, number[]>} */
        const batches = Object.create(null);

        /** Invalidate the entire display name cache (called on action manager updates). */
        function clearCache() {
            cache = Object.create(null);
        }

        env.bus.addEventListener("ACTION_MANAGER:UPDATE", clearCache);

        /**
         * Get or create the id→Promise mapping for a model.
         * @param {string} resModel
         * @returns {Record<string, Promise>}
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
                const { promise, resolve } = Promise.withResolvers();
                resolve(displayNames[resId]);
                mapping[resId] = promise;
            }
        }

        /**
         * @param {string} resModel valid resModel name
         * @param {number[]} resIds valid ids
         * @returns {Promise<DisplayNames>}
         */
        /** @type {Record<string, Record<string, { resolve: Function, reject: Function }>>} */
        const resolvers = Object.create(null);
        function getResolvers(resModel) {
            if (!resolvers[resModel]) {
                resolvers[resModel] = Object.create(null);
            }
            return resolvers[resModel];
        }

        async function loadDisplayNames(resModel, resIds) {
            const mapping = getMapping(resModel);
            const resModelResolvers = getResolvers(resModel);
            const proms = [];
            const resIdsToFetch = [];
            for (const resId of unique(resIds)) {
                if (!isId(resId)) {
                    throw new Error(`Invalid ID: ${resId}`);
                }
                if (!(resId in mapping)) {
                    const { promise, resolve, reject } = Promise.withResolvers();
                    mapping[resId] = promise;
                    resModelResolvers[resId] = { resolve, reject };
                    resIdsToFetch.push(resId);
                }
                proms.push(mapping[resId]);
            }
            if (resIdsToFetch.length) {
                if (batches[resModel]) {
                    batches[resModel].push(...resIdsToFetch);
                } else {
                    batches[resModel] = resIdsToFetch;
                    await Promise.resolve();
                    const idsInBatch = unique(batches[resModel]);
                    delete batches[resModel];

                    const specification = { display_name: {} };
                    orm.silent
                        .webSearchRead(resModel, [["id", "in", idsInBatch]], {
                            specification,
                            context: { active_test: false },
                        })
                        .then(({ records }) => {
                            const displayNames = Object.fromEntries(
                                records.map((rec) => [rec.id, rec.display_name]),
                            );
                            for (const resId of idsInBatch) {
                                resModelResolvers[resId].resolve(
                                    resId in displayNames
                                        ? displayNames[resId]
                                        : ERROR_INACCESSIBLE_OR_MISSING,
                                );
                                delete resModelResolvers[resId];
                            }
                        })
                        .catch((error) => {
                            for (const resId of idsInBatch) {
                                if (resModelResolvers[resId]) {
                                    resModelResolvers[resId].reject(error);
                                    delete resModelResolvers[resId];
                                    delete mapping[resId];
                                }
                            }
                        });
                }
            }
            const names = await Promise.all(proms);
            return Object.fromEntries(zip(resIds, names));
        }

        return { addDisplayNames, clearCache, loadDisplayNames };
    },
};

registry.category("services").add("name", nameService);
