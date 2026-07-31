// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/urgent_save_coordinator */

import { ModelEvent } from "@web/core/events";
import { SignalStore } from "@web/core/utils/reactive";

/**
 * @typedef {"idle" | "active"} UrgentSaveStatus
 * @typedef {"begin" | "end"} UrgentSaveEvent
 */

/**
 * @type {Record<UrgentSaveStatus, Partial<Record<UrgentSaveEvent, UrgentSaveStatus>>>}
 */
const TRANSITIONS = {
    idle: { begin: "active" },
    active: { end: "idle" },
};

export class InvalidUrgentSaveTransitionError extends Error {
    /**
     * @param {string} from
     * @param {string} event
     */
    constructor(from, event) {
        super(
            `UrgentSaveCoordinator: invalid transition '${event}' from state '${from}'`,
        );
        this.name = "InvalidUrgentSaveTransitionError";
        this.from = from;
        this.event = event;
    }
}

export class UrgentSaveCoordinator extends SignalStore {
    /**
     * @param {{ trigger: (event: string, payload?: any) => void } | null} [bus]
     */
    constructor(bus = null) {
        super();
        /** @type {UrgentSaveStatus} */
        this.status = "idle";
        this._bus = bus;
        /**
         * @type {Promise<unknown>[]}
         */
        this._reentrantProms = [];
    }

    /** @returns {boolean} */
    get isActive() {
        return this.status === "active";
    }

    /**
     * @param {UrgentSaveEvent} event
     */
    _transition(event) {
        const next = TRANSITIONS[this.status]?.[event];
        if (next === undefined) {
            throw new InvalidUrgentSaveTransitionError(this.status, event);
        }
        this.status = next;
    }

    /**
     * @template T
     * @param {() => Promise<T>} fn
     * @returns {Promise<T>}
     */
    async run(fn) {
        if (this.isActive) {
            const prom = fn();
            this._reentrantProms.push(prom);
            return prom;
        }
        this._transition("begin");
        this._reentrantProms = [];
        /** @type {Promise<any>[]} */
        const proms = [];
        this._bus?.trigger(ModelEvent.WILL_SAVE_URGENTLY, { proms });
        try {
            await Promise.allSettled(proms);
            return await fn();
        } finally {
            while (this._reentrantProms.length) {
                const reentrant = this._reentrantProms;
                this._reentrantProms = [];
                await Promise.allSettled(reentrant);
            }
            this._transition("end");
        }
    }

    /**
     * @template T
     * @param {Promise<T> | undefined} promise
     * @returns {Promise<T | undefined>}
     */
    async awaitUnlessUrgent(promise) {
        if (this.isActive) {
            Promise.resolve(promise).catch(() => {});
            return undefined;
        }
        return promise;
    }

    /**
     * @template T
     * @param {() => T | Promise<T>} fn
     * @returns {T | undefined | Promise<T>}
     */
    unlessUrgent(fn) {
        if (this.isActive) {
            return undefined;
        }
        return fn();
    }
}
