// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/urgent_save_coordinator - Observable urgent-save state machine for RelationalModel */

import { ModelEvent } from "@web/core/events";
import { SignalStore } from "@web/core/utils/reactive";

/**
 * Observable state machine for the urgent-save axis of a {@link RelationalModel}.
 * Replaces the bare ``model._urgentSave`` boolean with the same Coordinator
 * pattern as ``FormSaveCoordinator``/``SampleDataCoordinator``: transitions are
 * guarded and wrapped in {@link run}, centralizing the try/finally that
 * prevents a leaked flag on throw, plus SignalStore observability. Fires
 * ``ModelEvent.WILL_SAVE_URGENTLY`` on entry so concurrent field/editor
 * consumers can flush pending state synchronously.
 *
 * Does NOT replace the model's ``mutex`` or ``keepLast`` — this is a *mode*
 * flag, not a concurrency primitive. The *load* axis has no coordinator: it's
 * governed by ``loadId`` epochs in ``_getCacheParams``, not a flag.
 *
 * @typedef {"idle" | "active"} UrgentSaveStatus
 *
 * @typedef {"begin" | "end"} UrgentSaveEvent
 */

/**
 * Allowed status transitions. ``_transition`` looks up
 * ``TRANSITIONS[status]?.[event]``; ``undefined`` throws
 * {@link InvalidUrgentSaveTransitionError} instead of corrupting state
 * silently. Nested ``run()`` calls (re-entering ``begin`` from ``active``)
 * are treated as a programming error — urgent-save is tab-close-scoped, and
 * the browser never fires two concurrent tab-close handlers.
 *
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
     * @param {{ bus: { trigger: (event: string, payload?: any) => void } } | null} [bus]
     *   Optional event bus used to fire ``WILL_SAVE_URGENTLY`` at
     *   entry.  In the production RelationalModel this is
     *   ``model.bus``; tests can pass ``null`` to opt out.
     */
    constructor(bus = null) {
        super();
        /** @type {UrgentSaveStatus} */
        this.status = "idle";
        this._bus = bus;
    }

    /** @returns {boolean} true while a tab-close urgent save is in progress */
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
     * Run ``fn`` with the urgent-save mode active.  Sets ``status``
     * to ``"active"``, fires the bus event so concurrent field /
     * editor consumers can flush their pending state, then awaits
     * ``fn`` and resets status — even on throw.  The single point of
     * access for entering urgent-save mode.
     *
     * @template T
     * @param {() => Promise<T>} fn
     * @returns {Promise<T>}
     */
    async run(fn) {
        this._transition("begin");
        // Await consumer flushes BEFORE ``fn`` runs: a field whose onchange is
        // still in flight re-commits its value on this event, but async (mutex-
        // bypassed ``update`` -> ``_update``); without awaiting it, the save would
        // read empty ``_changes`` and silently drop the pending edit on tab close.
        // We await only these flush promises, NOT ``model.mutex`` — it may be held
        // by the very onchange we're bypassing, which would deadlock.
        const proms = [];
        this._bus?.trigger(ModelEvent.WILL_SAVE_URGENTLY, { proms });
        try {
            // Best-effort: a rejecting flush must not abort the tab-close save
            // (that would drop other consumers' already-committed edits).
            await Promise.allSettled(proms);
            return await fn();
        } finally {
            this._transition("end");
        }
    }

    /**
     * Inversion-of-control helper: await ``promise`` only when NOT in
     * urgent-save mode; while urgent, returns immediately so callers
     * (e.g. ``record._update`` awaiting async preprocessors) don't block
     * the tab-close race. Centralizes the check that would otherwise be
     * scattered across every consumer, which previously wrote::
     *
     *     if (!model.urgentSave.isActive) {
     *         await prom;
     *     }
     *
     * Does NOT cancel the underlying promise — it keeps running but the
     * caller no longer awaits it. Use {@link unlessUrgent} when the work
     * itself should be skipped, not just the await.
     *
     * @template T
     * @param {Promise<T> | undefined} promise
     * @returns {Promise<T | undefined>} resolves to ``undefined`` when
     *   urgent (caller would have skipped the await anyway); otherwise
     *   to whatever ``promise`` resolves to.
     */
    async awaitUnlessUrgent(promise) {
        if (this.isActive) {
            return undefined;
        }
        return promise;
    }

    /**
     * Inversion-of-control helper: invoke ``fn()`` only when NOT in
     * urgent-save mode, skipping it entirely (returning ``undefined``
     * synchronously) for skippable network round trips (onchange RPC,
     * validation flush) the urgent path has no time to await.
     *
     * Unlike {@link awaitUnlessUrgent} (which lets already-started work run
     * but un-awaits it), this prevents the work from starting at all — use
     * it for side-effecting RPCs that shouldn't fire on tab close.
     *
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
