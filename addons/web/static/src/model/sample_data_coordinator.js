// @ts-check
/** @odoo-module native */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * @typedef {"off" | "active"} SampleStatus
 */

export class SampleDataCoordinator extends SignalStore {
    constructor() {
        super();
        /** @type {SampleStatus} */
        this.status = "off";
    }

    /** @returns {boolean} */
    get isActive() {
        return this.status === "active";
    }

    enter() {
        this.status = "active";
    }

    exit() {
        this.status = "off";
    }

    /**
     * @param {boolean} value
     */
    set(value) {
        if (value) {
            this.enter();
        } else {
            this.exit();
        }
    }
}
