// @ts-check
/** @odoo-module native */

/** @module @web/model/sample_data_coordinator - Observable sample-mode state machine for Model */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * Observable state machine for the sample-data axis of a {@link Model}.
 * Replaces the bare ``model.useSampleModel`` boolean with the Coordinator
 * pattern used elsewhere in the model layer ({@link UrgentSaveCoordinator}).
 * The *load* axis of RelationalModel has no equivalent coordinator — it's
 * governed by ``loadId`` epochs in ``_loadData``/``_getCacheParams`` instead.
 *
 * ``Model`` keeps ``useSampleModel`` as a getter/setter delegating to this
 * coordinator for backward compatibility with existing read/write sites
 * ({@link PivotModel}, {@link GraphModel} write via {@link enter}/{@link exit}).
 *
 * Owns only the active/off flag and ``isActive``; does NOT own the
 * sample-server instance or decide when sample mode activates — that stays
 * on each Model subclass. State is just ``off ⇄ active`` (no epoch counter)
 * since sample mode is always set/cleared synchronously.
 *
 * @typedef {"off" | "active"} SampleStatus
 */

export class SampleDataCoordinator extends SignalStore {
    constructor() {
        super();
        /** @type {SampleStatus} */
        this.status = "off";
    }

    /** @returns {boolean} true while the model is serving sample data */
    get isActive() {
        return this.status === "active";
    }

    /** Activate sample mode. Idempotent — repeated entries are no-ops. */
    enter() {
        this.status = "active";
    }

    /** Deactivate sample mode. Idempotent — repeated exits are no-ops. */
    exit() {
        this.status = "off";
    }

    /**
     * Mirror ``useSampleModel = bool`` assignment used by PivotModel/GraphModel
     * write sites. Truthy activates, falsy deactivates.
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
