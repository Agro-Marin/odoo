// @ts-check
/** @odoo-module native */

/** @module @web/model/sample_data_coordinator - Observable sample-mode state machine for Model */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * Observable state machine for the sample-data axis of a {@link Model}.
 *
 * Replaces the bare ``model.useSampleModel`` boolean with the
 * Coordinator pattern used elsewhere in the model layer
 * ({@link RelationalModelLoadCoordinator}, {@link UrgentSaveCoordinator},
 * {@link FormSaveCoordinator}).
 *
 * **Backward compatibility**: ``Model`` keeps ``useSampleModel`` as
 * a getter/setter pair that delegates to this coordinator. The
 * historical 11 read-sites across the views layer (pivot_controller,
 * list_renderer, list_keyboard_nav, list_controller, kanban
 * renderer, etc.) continue to work unchanged via the getter; the
 * two write-sites in {@link PivotModel} and {@link GraphModel}
 * route through the setter into {@link enter} / {@link exit}.
 *
 * **Scope** — what this coordinator does AND does NOT do:
 *
 *   - **Does**: own the active / off flag for the sample-data mode,
 *     expose ``isActive`` for readers, and serve as the singleton
 *     event surface that future debug tooling can subscribe to.
 *
 *   - **Does NOT** own the sample-server instance (``sample_server.js``)
 *     or decide *when* sample mode should activate — those remain on
 *     the specific Model subclass (RelationalModel, PivotModel,
 *     GraphModel each have their own activation policy).
 *
 * The state machine is intentionally simpler than the Load
 * coordinator: only ``off ⇄ active`` with no epoch counter, because
 * sample mode is set/cleared from synchronous code paths (no async
 * race between concurrent entries to worry about).
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
     * Mirror ``useSampleModel = bool`` assignment for the two write
     * sites in PivotModel / GraphModel that currently do
     * ``this.useSampleModel = false``.  Truthy values activate, falsy
     * deactivate — same semantics as the underlying boolean.
     *
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
