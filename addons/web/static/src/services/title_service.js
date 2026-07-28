// @ts-check
/** @odoo-module native */

/** @module @web/services/title_service - Manages the document title with named parts and notification counters */

/**
 * @typedef {Object} TitleServiceAPI
 * @property {string} current - the current document.title value (readonly)
 * @property {() => Record<string, string>} getParts - get a copy of the title parts
 * @property {(counters: Record<string, number>) => void} setCounters - set notification counters
 * @property {(parts: Record<string, string | null>) => void} setParts - set title segments
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
         * Return a shallow copy of the current title parts.
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

        /** @returns {string} the title this service's state describes */
        function computeTitle() {
            const counter = Object.values(titleCounters).reduce(
                (acc, count) => acc + count,
                0,
            );
            const name = Object.values(titleParts).join(" - ") || "Odoo";
            return counter ? `(${counter}) ${name}` : name;
        }

        /** Recompute document.title from parts and counters. */
        function updateTitle() {
            const title = computeTitle();
            // Assigning document.title unconditionally re-enters the browser's
            // title machinery (and fires a DOM mutation observed by tooling) on
            // every setParts/setCounters call, most of which are no-ops.
            if (document.title !== title) {
                document.title = title;
            }
        }

        return {
            /**
             * The title this service's own parts and counters describe.
             *
             * Reads the computed value, NOT ``document.title``: anything else on
             * the page that writes the DOM title (a third-party script, a tour,
             * a stray `document.title =`) used to make `current` contradict
             * `getParts()` with no way for a caller to tell which was authoritative.
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
