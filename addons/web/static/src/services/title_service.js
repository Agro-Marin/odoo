// @ts-check
/** @odoo-module native */

/** @module @web/services/title_service */

/**
 * @typedef {Object} TitleServiceAPI
 * @property {string} current
 * @property {() => Record<string, string>} getParts
 * @property {(counters: Record<string, number>) => void} setCounters
 * @property {(parts: Record<string, string | null>) => void} setParts
 */

import { registry } from "@web/core/registry";
export const titleService = {
    /** @returns {TitleServiceAPI} */
    start() {
        /** @type {Record<string, number>} */
        const titleCounters = {};
        /** @type {Record<string, string>} */
        const titleParts = {};

        /**
         * @returns {Record<string, string>}
         */
        function getParts() {
            return { ...titleParts };
        }

        /**
         * @param {Record<string, number>} counters
         */
        function setCounters(counters) {
            for (const [key, val] of Object.entries(counters)) {
                if (!val) {
                    delete titleCounters[key];
                } else {
                    titleCounters[key] = val;
                }
            }
            updateTitle();
        }

        /**
         * @param {Record<string, string | null>} parts
         */
        function setParts(parts) {
            for (const [key, val] of Object.entries(parts)) {
                if (!val) {
                    delete titleParts[key];
                } else {
                    titleParts[key] = val;
                }
            }
            updateTitle();
        }

        /** @returns {string} */
        function computeTitle() {
            const counter = Object.values(titleCounters).reduce(
                (acc, count) => acc + count,
                0,
            );
            const name = Object.values(titleParts).join(" - ") || "Odoo";
            return counter ? `(${counter}) ${name}` : name;
        }

        function updateTitle() {
            const title = computeTitle();
            if (document.title !== title) {
                document.title = title;
            }
        }

        return {
            /**
             * @returns {string}
             */
            get current() {
                return computeTitle();
            },
            getParts,
            setCounters,
            setParts,
        };
    },
};

registry.category("services").add("title", titleService);
