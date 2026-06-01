// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/load_coordinator - Tracks the load lifecycle of a RelationalModel as an observable state machine */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * Make the implicit load lifecycle of a {@link RelationalModel} observable.
 *
 * Mirrors {@link FormSaveCoordinator} (views/form/form_save_coordinator)
 * with the same TRANSITIONS-table + epoch-counter + named-error
 * pattern, applied to the load axis of the model rather than the save
 * axis of the form.
 *
 * Scope (what this coordinator does AND does NOT do):
 *
 *   - **Does**: track an observable ``status`` (``idle | loading |
 *     error``) so external readers (loading indicators, route guards,
 *     debug surfaces) can subscribe without reverse-engineering
 *     three flags. Guard illegal transitions (e.g. ``ok`` from
 *     ``idle``) so latent misroutings surface as
 *     {@link InvalidLoadTransitionError} instead of silent status
 *     corruption.
 *
 *   - **Does NOT** replace the proven concurrency primitives that
 *     ``RelationalModel`` uses for different orthogonal concerns:
 *     * ``model.keepLast`` — drops stale loads when navigation
 *       supersedes an in-flight request. Cancellation semantics, not
 *       state tracking.
 *     * ``model.mutex`` — serializes per-record save/discard critical
 *       sections (the model's ``Mutex`` is shared by every record
 *       in the data graph). A coordinator at the model level cannot
 *       replace mutex usage scattered across {@link RelationalRecord}
 *       without an unrelated re-architecting.
 *     * ``model._urgentSave`` — cross-cutting mode flag read by ~5
 *       fast-paths in record/save/preprocessors. Different axis
 *       (urgent save vs. load).
 *
 * The audit that motivated this coordinator (recommendation #9)
 * framed it as a replacement for those three primitives. Reading the
 * code revealed that the framing conflated concerns; this
 * implementation keeps the existing primitives and ADDS the
 * coordinator as a narration layer. Same trade-off as the ``ChangeSet``
 * extraction (which kept ``record.dirty`` as a public field while
 * formalizing the atomic ``changes/dirty`` pair via paired helpers).
 *
 * @typedef {"idle" | "loading" | "error"} LoadStatus
 *
 * @typedef {"begin" | "ok" | "failed" | "discard"} LoadEvent
 */

/**
 * Allowed status transitions, keyed by source state. ``_transition``
 * looks up ``TRANSITIONS[status]?.[event]``; ``undefined`` means the
 * event is not declared valid from the current state and the
 * coordinator throws {@link InvalidLoadTransitionError} instead of
 * silently corrupting status.
 *
 * Notable cells:
 *
 *   - ``loading → begin → loading``: a second ``requestLoad`` while a
 *     prior load is still in flight (the existing ``keepLast`` will
 *     drop the prior load; the coordinator's epoch counter ensures
 *     the prior load's terminal event is treated as a stale no-op).
 *   - ``loading → discard → idle``: external cancellation (e.g.
 *     controller unmount aborts the current load). The terminal
 *     event of the cancelled load is dropped by the epoch guard.
 *   - ``error → begin → loading``: retry after a failure. No
 *     intermediate "clear error" step required.
 *
 * Omitted cells (e.g. ``ok`` from ``idle``) catch programming errors:
 * routing a load-completion outcome without ever entering ``loading``
 * indicates a misrouted call path.
 *
 * @type {Record<LoadStatus, Partial<Record<LoadEvent, LoadStatus>>>}
 */
const TRANSITIONS = {
    idle:    { begin: "loading", discard: "idle" },
    loading: { begin: "loading", ok: "idle", failed: "error", discard: "idle" },
    error:   { begin: "loading", discard: "idle" },
};

export class InvalidLoadTransitionError extends Error {
    /**
     * @param {string} from
     * @param {string} event
     */
    constructor(from, event) {
        super(`RelationalModelLoadCoordinator: invalid transition '${event}' from state '${from}'`);
        this.name = "InvalidLoadTransitionError";
        this.from = from;
        this.event = event;
    }
}

/**
 * Observable state machine for the load axis of a RelationalModel.
 *
 * Extends ``SignalStore`` so external consumers can subscribe to
 * ``coordinator.status`` and ``coordinator.lastError`` through OWL's
 * reactivity — e.g. a global loading-spinner component that reads
 * ``model.loadCoordinator.status === "loading"`` and re-renders on
 * change.
 */
export class RelationalModelLoadCoordinator extends SignalStore {
    /** @type {LoadStatus} */
    status = "idle";

    /** @type {any | null} Last unhandled load error, surfaced for diagnostics. */
    lastError = null;

    /**
     * Monotonic counter incremented on every ``begin`` (new load in
     * flight) and every ``discard`` (in-flight load invalidated by
     * external cancellation). Each load captures its own
     * ``_loadEpoch`` on entry; its terminal event (``ok`` / ``failed``)
     * is silently dropped when the current epoch has moved on, because
     * the state has already been settled by a concurrent load or
     * discard. Mirrors ``FormSaveCoordinator._saveEpoch``.
     *
     * @type {number}
     */
    _loadEpoch = 0;

    /** @returns {boolean} true while a load is in flight */
    get isLoading() {
        return this.status === "loading";
    }

    /**
     * Apply a status transition with a guard. Throws
     * {@link InvalidLoadTransitionError} if ``event`` is not declared
     * valid from the current state in {@link TRANSITIONS}. Every
     * status write inside this class must go through here so latent
     * misroutings surface immediately instead of corrupting
     * downstream observers.
     *
     * External direct writes to ``this.status`` (e.g. from tests
     * forcing a starting state) bypass the guard by design.
     *
     * @param {LoadEvent} event
     */
    _transition(event) {
        const next = TRANSITIONS[this.status]?.[event];
        if (next === undefined) {
            throw new InvalidLoadTransitionError(this.status, event);
        }
        this.status = next;
    }

    /**
     * Terminal-event helper. Routes ``ok`` / ``failed`` through
     * {@link _transition} only when ``ownerEpoch`` is still the
     * current ``_loadEpoch``. Concurrent loads and mid-load discards
     * bump the epoch, so the losing load's terminal becomes a no-op
     * instead of either throwing or corrupting the now-settled
     * status.
     *
     * @param {LoadEvent} event
     * @param {number} ownerEpoch the epoch claimed by the caller's ``_transition("begin")``
     */
    _finishTransition(event, ownerEpoch) {
        if (ownerEpoch !== this._loadEpoch) {
            return;
        }
        this._transition(event);
    }

    /**
     * Drive a load operation through the state machine.
     *
     * Resolves the same value the inner ``loadFn`` resolves; rejects
     * with the same error (the coordinator doesn't swallow). The
     * status side-effects happen as a side-channel observable.
     *
     * Usage from ``RelationalModel.load``:
     *
     * ```js
     * await this.loadCoordinator.run(() => this.keepLast.add(this._loadData(config, cache)));
     * ```
     *
     * @template T
     * @param {() => Promise<T>} loadFn the underlying load work — usually
     *   wraps ``keepLast.add(_loadData(...))`` so the existing
     *   cancellation semantics are preserved.
     * @returns {Promise<T>}
     */
    async run(loadFn) {
        this.lastError = null;
        this._transition("begin");
        const ownerEpoch = ++this._loadEpoch;
        try {
            const result = await loadFn();
            this._finishTransition("ok", ownerEpoch);
            return result;
        } catch (error) {
            this.lastError = error;
            this._finishTransition("failed", ownerEpoch);
            throw error;
        }
    }

    /**
     * Mark any in-flight load as cancelled. Caller is responsible for
     * actually cancelling the underlying work (typically by issuing a
     * new ``keepLast.add(...)`` on the model). Bumps the epoch so the
     * cancelled load's terminal becomes a stale no-op.
     */
    discard() {
        if (this.status === "loading") {
            this._loadEpoch++;
        }
        this._transition("discard");
    }
}
