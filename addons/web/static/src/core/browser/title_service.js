// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/title_service */

// `TitleServiceAPI` used to be declared here: a hand-written typedef for the
// object literal `start()` returned, because a literal has no type of its own.
// `TitleService` is that type now, derived from the implementation.

import { registry } from "@web/core/registry";

/**
 * The `title` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * `_computeTitle` and `_updateTitle` are underscored because the literal
 * published only `{ current, getParts, setCounters, setParts }` and kept them
 * inside. A class exposes every prototype method, so leaving the names bare
 * would widen the service's surface — hazard 6.
 */
export class TitleService {
    constructor() {
        /** @type {Record<string, number>} */
        this.titleCounters = {};
        /** @type {Record<string, string>} */
        this.titleParts = {};
    }

    /** @returns {string} */
    get current() {
        return this._computeTitle();
    }

    /**
     * @returns {Record<string, string>}
     */
    getParts() {
        return { ...this.titleParts };
    }

    /**
     * @param {Record<string, number>} counters
     */
    setCounters(counters) {
        for (const [key, val] of Object.entries(counters)) {
            if (!val) {
                delete this.titleCounters[key];
            } else {
                this.titleCounters[key] = val;
            }
        }
        this._updateTitle();
    }

    /**
     * @param {Record<string, string | null>} parts
     */
    setParts(parts) {
        for (const [key, val] of Object.entries(parts)) {
            if (!val) {
                delete this.titleParts[key];
            } else {
                this.titleParts[key] = val;
            }
        }
        this._updateTitle();
    }

    /** @returns {string} */
    _computeTitle() {
        const counter = Object.values(this.titleCounters).reduce(
            (acc, count) => acc + count,
            0,
        );
        const name = Object.values(this.titleParts).join(" - ") || "Odoo";
        return counter ? `(${counter}) ${name}` : name;
    }

    _updateTitle() {
        const title = this._computeTitle();
        if (document.title !== title) {
            document.title = title;
        }
    }
}

export const titleService = {
    /** @returns {TitleService} */
    start() {
        return new TitleService();
    },
};

registry.category("services").add("title", titleService);
