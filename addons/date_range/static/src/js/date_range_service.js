/** @odoo-module native */
import { registry } from "@web/core/registry";

export const dateRangeService = {
    dependencies: ["orm"],

    /**
     * Start the date_range service
     *
     * @param {Object} env - Odoo environment
     * @param {Object} deps - Service dependencies
     * @param {Object} deps.orm - ORM service for database access
     * @returns {Object} Service API with loadDateRanges method
     */
    async start(env, { orm }) {
        let cache = null;
        let loading = null;

        /**
         * Load date ranges and types from backend.
         * Uses caching to avoid redundant API calls.
         *
         * @returns {Promise<Object>} Object with ranges and types arrays
         * @returns {Array} ranges - Array of date.range records
         * @returns {Array} types - Array of date.range.type records
         *
         * @example
         * const { ranges, types } = await dateRangeService.loadDateRanges();
         * console.log(ranges); // [{ id: 1, name: "Q1 2024", ... }, ...]
         */
        async function loadDateRanges() {
            // Return cached data if available
            if (cache) {
                return cache;
            }

            // Return ongoing loading promise if already loading
            if (loading) {
                return loading;
            }

            // Start new loading process
            loading = Promise.all([
                orm.searchRead(
                    "date.range",
                    [["active", "=", true]],
                    ["id", "name", "type_id", "date_start", "date_end"],
                    {
                        order: "type_id, date_start",
                    },
                ),
                orm.searchRead(
                    "date.range.type",
                    [],
                    ["id", "name", "date_ranges_exist"],
                    { order: "name" },
                ),
            ])
                .then(([ranges, types]) => {
                    // Cache the results
                    cache = { ranges, types };
                    loading = null;
                    return cache;
                })
                .catch((error) => {
                    // Clear loading state on error so retry is possible
                    loading = null;
                    throw error;
                });

            return loading;
        }

        return {
            loadDateRanges,
        };
    },
};

// Register the service
registry.category("services").add("date_range", dateRangeService);
