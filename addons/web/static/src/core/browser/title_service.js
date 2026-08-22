// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

class TitleService {
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
