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
 * silently. There is deliberately no ``active -> begin``: a re-entrant
 * ``run()`` (a second ``urgentSave()`` on the SAME model) is NOT a
 * transition — ``run`` short-circuits it before ``_transition`` (see
 * ``run``), so the flag is only ever raised and lowered once, by the
 * outermost entry.
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
        /**
         * Promises of re-entrant ``run()`` calls (a second ``urgentSave()`` on
         * the SAME model while urgent mode is already active). The OUTERMOST
         * entry awaits these in its ``finally`` before lowering the flag, so
         * urgent mode covers their whole lifetime.
         * @type {Promise<unknown>[]}
         */
        this._reentrantProms = [];
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
        if (this.isActive) {
            // Re-entrant call: a second ``urgentSave()`` on the SAME model
            // (e.g. an edited row and a running timer datapoint both calling
            // ``.urgentSave()`` inside a ``Promise.all`` on tab close) arrives
            // while urgent mode is already active. The mode flag is set and
            // ``WILL_SAVE_URGENTLY`` already fired for the outermost entry, so
            // just run ``fn`` under the active mode. Re-transitioning ``begin``
            // would throw {@link InvalidUrgentSaveTransitionError}, rejecting
            // this call so its beacon never fires (lost edits) and failing the
            // whole ``Promise.all`` during unload. Only the outermost entry
            // owns the try/finally that resets the flag.
            //
            // Track this promise so the outermost entry's ``finally`` awaits it
            // before transitioning to ``idle``: if this re-entrant save has
            // awaits (inDialog, or the new-record webSave path with a hook) and
            // the outer ``fn`` resolves first, the flag would drop mid-flight
            // and remaining ``isActive`` checks would flip to non-urgent (e.g.
            // an onchange RPC could then fire during unload).
            const prom = fn();
            this._reentrantProms.push(prom);
            return prom;
        }
        this._transition("begin");
        // Fresh collector for this urgent-mode window (only one outermost entry
        // is ever active at a time — the status guard above serializes them).
        this._reentrantProms = [];
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
            // Best-effort: keep urgent mode active until every re-entrant save
            // kicked off under this entry has settled, so none of them observe
            // ``isActive === false`` mid-flight. A rejecting re-entrant save
            // must not abort the transition (its own caller already owns the
            // rejection), hence ``allSettled``.
            const reentrant = this._reentrantProms;
            this._reentrantProms = [];
            await Promise.allSettled(reentrant);
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
            // The caller stops awaiting, so a later rejection of `promise`
            // would surface as an unhandled rejection (→ an error dialog on
            // tab close). Attach a no-op catch: the work is intentionally
            // fire-and-forget here.
            Promise.resolve(promise).catch(() => {});
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
