// @ts-check
/** @odoo-module native */

/**
 * @typedef {"idle" | "saving"} RecordSaveStatus
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
     * @returns {boolean}
     */
    get beaconFired() {
        return this._beaconFired;
    }

    /** @returns {void} */
    noteBeaconFired() {
        this._beaconFired = true;
    }

    /** @returns {void} */
    clearBeacon() {
        this._beaconFired = false;
    }

    /**
     * @returns {boolean}
     */
    consumeBeaconFired() {
        const fired = this._beaconFired;
        this._beaconFired = false;
        return fired;
    }
}
