// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/urgent_save_coordinator - Observable urgent-save state machine for RelationalModel */

import { ModelEvent } from "@web/core/events";
import { SignalStore } from "@web/core/utils/reactive";

/**
 * Observable state machine for the urgent-save axis of a
 * {@link RelationalModel}.
 *
 * Replaces the bare ``model._urgentSave`` boolean with the same
 * Coordinator pattern used by ``FormSaveCoordinator`` (views/form)
 * and ``SampleDataCoordinator``: explicit status field, guarded
 * transitions, observable via SignalStore so external readers
 * (debug overlay, future feature-flag-gated UI) can subscribe.
 * (There is no coordinator for the *load* axis: that axis is governed
 * by ``loadId`` epochs stamped in ``_loadData`` plus the root-swap /
 * ``loadId`` guards in ``_getCacheParams``, with ``keepLast``
 * cancelling stale loads — see ``relational_model.js``.)
 *
 * **Scope** — what this coordinator does AND does NOT do:
 *
 *   - **Does**: own the ``active | idle`` flag for the urgent-save
 *     mode, expose it as ``isActive`` for readers, and wrap entry
 *     in {@link run} so the try/finally bookkeeping that prevents
 *     a leaked flag on throw stays in one place. Fires the bus
 *     event ``ModelEvent.WILL_SAVE_URGENTLY`` on entry so concurrent
 *     field / editor consumers can flush their pending state
 *     synchronously — same lifecycle the bare-flag implementation
 *     had, just centralized.
 *
 *   - **Does NOT** replace the model's ``mutex`` (per-record
 *     save/discard serialization) or its ``keepLast`` (cancellation
 *     of stale loads). Urgent-save is a *mode* flag read by ~5
 *     fast-paths; those are *concurrency* primitives.
 *
 * **Why not just keep a boolean** — three load-bearing pieces:
 *
 *   1. The try/finally guard around the boolean is easy to forget.
 *      Three sites (a hypothetical future direct assignment) would
 *      reintroduce the leak the existing comment block in
 *      ``relational_model.js`` warns against. Putting entry behind
 *      ``coordinator.run(fn)`` removes the option to leak.
 *
 *   2. Observability: SignalStore reactivity means a future
 *      "saving urgently…" indicator binds without bus plumbing.
 *
 *   3. Symmetry with ``FormSaveCoordinator`` and
 *      ``SampleDataCoordinator``: the mode axes that are plain flags
 *      (save, sample-data, urgent-save) follow the same shape. The
 *      load axis intentionally has no coordinator — it is not a flag
 *      but a sequence of epochs (``config.loadId``) guarded in
 *      ``_getCacheParams`` against root swaps and superseded loads.
 *
 * @typedef {"idle" | "active"} UrgentSaveStatus
 *
 * @typedef {"begin" | "end"} UrgentSaveEvent
 */

/**
 * Allowed status transitions. ``_transition`` looks up
 * ``TRANSITIONS[status]?.[event]``; ``undefined`` means the event
 * is not declared valid from the current state and the coordinator
 * throws {@link InvalidUrgentSaveTransitionError} instead of
 * corrupting state silently.
 *
 * Nested ``run()`` calls would re-enter ``begin`` from ``active``,
 * which we treat as a programming error — the urgent-save mode is
 * tab-close-scoped, so two concurrent entries would mean two
 * concurrent tab-close handlers, which the browser doesn't allow.
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
        // Collect and await consumer flushes BEFORE running ``fn``.  A field
        // whose onchange is still in flight re-commits its value on this event
        // (``input_field_hook``), but that re-commit is async (mutex-bypassed
        // ``update`` -> ``_update``).  The bus event is otherwise fire-and-
        // forget, so without awaiting the pushed promises ``fn`` (the save)
        // would read empty ``_changes`` and skip the sendBeacon — silently
        // dropping the pending edit on tab close.  We await only the consumer
        // promises here, NOT ``model.mutex`` (it may be held by the very
        // onchange we are bypassing, which would deadlock the tab-close save).
        const proms = [];
        this._bus?.trigger(ModelEvent.WILL_SAVE_URGENTLY, { proms });
        try {
            // Best-effort: a single consumer flush that rejects must not abort
            // the tab-close save (that would silently drop every other
            // consumer's already-committed edits). allSettled waits for all
            // flushes to settle without propagating a rejection.
            await Promise.allSettled(proms);
            return await fn();
        } finally {
            this._transition("end");
        }
    }

    /**
     * Inversion-of-control helper: await ``promise`` only when NOT in
     * urgent-save mode. While urgent, returns immediately so callers
     * (record._update awaiting async preprocessors, record.checkValidity
     * awaiting an _askChanges flush) don't block the tab-close race.
     *
     * Callers previously wrote::
     *
     *     if (!model.urgentSave.isActive) {
     *         await prom;
     *     }
     *
     * which spreads the skip-condition knowledge across every consumer.
     * Threading it through this method keeps the "what does urgent mode
     * skip?" answer on the coordinator — same encapsulation move the
     * existing ``run(fn)`` made for the write side of the flag.
     *
     * Does NOT cancel the underlying promise — it keeps running but the
     * caller no longer awaits it. Use {@link unlessUrgent} when the
     * work itself should be skipped (not just awaiting it).
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
     * urgent-save mode. Skips the call entirely while urgent, returning
     * ``undefined`` synchronously — useful for skippable network round
     * trips (e.g. onchange RPC, validation flush) that the urgent path
     * has no time to await.
     *
     * Compared to {@link awaitUnlessUrgent}: this prevents the work from
     * starting at all, where ``awaitUnlessUrgent`` lets the work run but
     * un-awaits it. Choose ``unlessUrgent`` for side-effecting RPCs that
     * shouldn't fire on tab close; choose ``awaitUnlessUrgent`` for
     * already-scheduled local work.
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
