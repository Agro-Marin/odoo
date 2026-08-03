// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_save_coordinator */

/**
 * @typedef {"idle" | "saving"} RecordSaveStatus
 */

/**
 * The save lifecycle of ONE record: whether a save is currently on the wire,
 * and whether the urgent-save beacon has already carried its changes.
 *
 * Distinct from `UrgentSaveCoordinator`, which is per-model and answers "is the
 * tab closing". This answers "has this record already been written", which two
 * different callers need and neither owns:
 *
 *  - `record.urgentSave()` must not fire a beacon for a record whose save is
 *    already on the wire, or the server takes the same changes twice.
 *  - `save()` parks in the `onWillSaveRecord` hook, which can await arbitrarily
 *    long. A beacon that fires while it is parked has already persisted the
 *    changes, so the resumed save must return rather than write them again.
 *
 * Deliberately NOT a `SignalStore`, unlike the other coordinators. Nothing
 * renders this state, and `record.urgentSave()` reads it through `toRaw()`
 * precisely to avoid taking a reactive dependency inside a `beforeunload`
 * handler. A reactive base would make that read subscribe again.
 */
export class RecordSaveCoordinator {
    constructor() {
        /** @type {RecordSaveStatus} */
        this.status = "idle";
        this._beaconFired = false;
    }

    /** @returns {boolean} */
    get isInFlight() {
        return this.status === "saving";
    }

    /** @returns {void} */
    enter() {
        this.status = "saving";
    }

    /** @returns {void} */
    exit() {
        this.status = "idle";
    }

    /**
     * Observation only. A caller deciding whether to skip a write must use
     * `consumeBeaconFired()`, so the flag cannot survive into the next save.
     *
     * @returns {boolean}
     */
    get beaconFired() {
        return this._beaconFired;
    }

    /** @returns {void} */
    noteBeaconFired() {
        this._beaconFired = true;
    }

    /** Forgets a beacon left over from an earlier save. @returns {void} */
    clearBeacon() {
        this._beaconFired = false;
    }

    /**
     * True at most once per beacon: reading it consumes the flag, so a stale
     * one cannot short-circuit the next real save.
     *
     * @returns {boolean}
     */
    consumeBeaconFired() {
        const fired = this._beaconFired;
        this._beaconFired = false;
        return fired;
    }
}
