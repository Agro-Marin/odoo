// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_save_coordinator - Centralizes the form view's save lifecycle as observable state */

/**
 * Owns the form's save lifecycle as observable reactive state, replacing the
 * historical pattern where every save-related entry point in
 * ``form_controller.js`` independently checked dirtiness, built its own
 * ``{ onError, reload, nextId, ... }`` argument bag, and routed errors
 * inconsistently. Today every entry point is a ~3-line method that calls
 * ``coordinator.requestSave({...})`` with named options; ``status`` is the
 * single observable surface (current consumer: ``FormStatusIndicator``).
 *
 * Out-of-contract callers: code that invokes ``model.root.save()`` /
 * ``root.discard()`` directly (several field widgets, e.g.
 * ``@web/fields/translation_button``) bypasses the coordinator entirely —
 * ``status`` will not reflect those saves. New form-level save paths must go
 * through ``requestSave`` / ``requestDiscard`` / ``requestUrgentSave``.
 *
 * Compares to React Admin's ``<SaveContextProvider>`` and Refine's
 * ``useForm`` — both expose ``{ saving, isDirty, mutationMode }`` as a
 * public, subscribable surface.
 */

import { SignalStore } from "@web/core/utils/reactive";

/**
 * @typedef {"clean" | "dirty" | "saving" | "error"} FormSaveStatus
 *
 * @typedef {"begin" | "ok" | "recoverable" | "failed" | "discard"} FormSaveEvent
 *
 * @typedef {{
 *   onSaveError: (error: any, callbacks: { discard: () => any, retry: () => any }) => any,
 *   onUrgentSaveFailed?: () => void,
 *   recoverFromSaveError?: (error: any, model: any) => boolean,
 * }} FormSaveHooks
 *
 * @typedef {{
 *   checkDirty?: boolean,
 *   reload?: boolean,
 *   nextId?: number,
 *   errorMode?: "dialog" | "rethrow" | "silent",
 *   saveOverride?: (record: any, params: any) => Promise<any>,
 *   params?: Record<string, any>,
 * }} RequestSaveOptions
 */

/**
 * Allowed status transitions, keyed by source state. ``_transition`` looks
 * up ``TRANSITIONS[status]?.[event]``; ``undefined`` means the event isn't
 * valid from the current state, and the coordinator throws
 * ``InvalidFormSaveTransitionError`` instead of silently corrupting status.
 *
 * ``saving → begin → saving`` is a no-op (concurrent ``requestSave``
 * re-entry under the mutex); ``error → begin → saving`` is the retry path.
 * Omitted cells (e.g. ``ok`` from ``clean``) catch programming errors —
 * routing a completion outcome without ever entering ``saving``.
 *
 * @type {Record<FormSaveStatus, Partial<Record<FormSaveEvent, FormSaveStatus>>>}
 */
const TRANSITIONS = {
    clean: { begin: "saving", discard: "clean" },
    dirty: { begin: "saving", discard: "clean" },
    saving: {
        begin: "saving",
        ok: "clean",
        recoverable: "dirty",
        failed: "error",
        discard: "clean",
    },
    error: { begin: "saving", discard: "clean" },
};

export class InvalidFormSaveTransitionError extends Error {
    /**
     * @param {string} from
     * @param {string} event
     */
    constructor(from, event) {
        super(
            `FormSaveCoordinator: invalid transition '${event}' from state '${from}'`,
        );
        this.name = "InvalidFormSaveTransitionError";
        this.from = from;
        this.event = event;
    }
}

export class FormSaveCoordinator extends SignalStore {
    /** @type {FormSaveStatus} */
    status = "clean";

    /**
     * The most recent save error, cleared only on entry to the next
     * ``requestSave`` / ``requestDiscard``.
     *
     * INVARIANT — do NOT clear this on a successful terminal, however wrong
     * the pairing looks. ``status: "clean"`` together with a non-null
     * ``lastError`` is a real state, not a leak: when a save fails and the
     * user answers the error dialog with "Discard changes", ``record.save``
     * RETURNS the hook's truthy result (``record_save.js`` does
     * ``return onError(...)``), so the save settles as ``ok`` even though
     * nothing was written. ``lastError`` is the only remaining evidence of
     * that, and ``FormController.shouldExecuteAction`` reads exactly this pair
     * to refuse the action the user had queued behind the save — pinned by
     * "don't duplicate if save fail" in ``views/form/form_view.test.js``.
     *
     * Clearing it here is unobservable in the OTHER direction: the sole reader
     * always issues its own ``requestSave`` first, and that resets the slot.
     *
     * @type {any | null}
     */
    lastError = null;

    /**
     * Monotonic counter bumped on every ``begin`` and every discard. Each
     * save/discard captures its own epoch on entry; its settlement is
     * silently dropped once the epoch has moved on, since the state has
     * already been settled by a concurrent save or discard. Misrouted
     * outcomes from outside ``requestSave`` / ``requestUrgentSave`` still
     * surface as ``InvalidFormSaveTransitionError``.
     *
     * @type {number}
     */
    _saveEpoch = 0;

    /**
     * @param {{ root: any }} model       FormController's relational model
     * @param {FormSaveHooks} hooks       Wired by the controller in setup()
     */
    constructor(model, hooks) {
        super();
        this.model = model;
        this.hooks = hooks;
    }

    /** @returns {boolean} true while a save / urgent-save is in flight */
    get isSaving() {
        return this.status === "saving";
    }

    /**
     * Real user-edit dirtiness, read straight from the model record. The
     * ``status`` state machine only observes COMMITTED save/discard outcomes
     * (by design — see the module docstring and STATE_MANAGEMENT.md), so a
     * record the user has typed into sits at ``status === "clean"`` while
     * ``record.dirty`` is already true. This getter gives future readers
     * (route guards, dialog blockers) a single truthful dirty surface without
     * folding uncommitted edits into the save-lifecycle status.
     *
     * @returns {boolean}
     */
    get dirty() {
        return Boolean(this.model.root?.dirty);
    }

    /**
     * Apply a status transition with a guard, throwing
     * ``InvalidFormSaveTransitionError`` if ``event`` is not valid from the
     * current state. Every status write inside this class must go through
     * here so latent misroutings surface immediately instead of corrupting
     * downstream observers. (External direct writes to ``this.status``,
     * e.g. from tests forcing a starting state, bypass the guard by design.)
     *
     * @param {FormSaveEvent} event
     */
    _transition(event) {
        const next = TRANSITIONS[this.status]?.[event];
        if (next === undefined) {
            throw new InvalidFormSaveTransitionError(this.status, event);
        }
        this.status = next;
    }

    /**
     * Terminal-event helper. Routes ``ok`` / ``recoverable`` / ``failed``
     * through ``_transition`` only when ``ownerEpoch`` is still current.
     * Concurrent saves and mid-save discards bump the epoch, so a losing
     * save's terminal becomes a no-op instead of corrupting settled status.
     *
     * @param {FormSaveEvent} event
     * @param {number} ownerEpoch the epoch claimed by the caller's ``_transition("begin")``
     */
    _finishTransition(event, ownerEpoch) {
        if (ownerEpoch !== this._saveEpoch) {
            return;
        }
        this._transition(event);
    }

    /**
     * Save the form record. All save-related entry points in
     * ``form_controller.js`` (and ``settings_form_controller.js``) route
     * through here. Field widgets that call ``model.root.save()`` directly
     * are out-of-contract — ``status`` / ``isSaving`` won't reflect those
     * saves (see the module docstring).
     *
     * Resolves to ``true`` on a successful save (or a ``checkDirty``
     * short-circuit), ``false`` when blocked/invalid/the dialog UX returned
     * "stay here", or the saveOverride / record.save return value when it's
     * a non-boolean (e.g. an action descriptor).
     *
     * Throws when ``errorMode === "rethrow"`` and ``record.save()`` raises,
     * AND whenever a ``saveOverride`` raises — an override owns its own error
     * contract, so its failure is never swallowed regardless of ``errorMode``
     * (this is the ``beforeLeave`` / ``save`` path in ``form_controller.js``).
     * Otherwise ("dialog", "silent") the error is captured in ``lastError``
     * and the call returns false.
     *
     * @param {RequestSaveOptions} [options]
     * @returns {Promise<any>}
     */
    async requestSave({
        checkDirty = false,
        reload = true,
        nextId,
        errorMode = "dialog",
        saveOverride,
        params,
    } = {}) {
        if (checkDirty && !(await this.model.root.isDirty())) {
            return true;
        }
        this.lastError = null;
        this._transition("begin");
        const ownerEpoch = ++this._saveEpoch;
        /** @type {Record<string, any>} */
        const opts = { reload, ...params };
        if (nextId !== undefined) {
            opts.nextId = nextId;
        }
        try {
            let saved;
            if (saveOverride) {
                saved = await saveOverride(this.model.root, opts);
            } else {
                const onError = this._buildOnError(errorMode, ownerEpoch);
                if (onError) {
                    opts.onError = onError;
                }
                saved = await this.model.root.save(opts);
            }
            if (saved !== false) {
                this._finishTransition("ok", ownerEpoch);
                return saved;
            }
            this._finishTransition("recoverable", ownerEpoch);
            return false;
        } catch (e) {
            this._finishTransition("failed", ownerEpoch);
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = e;
            }
            // global error handler so the failure surfaces.
            if (errorMode === "rethrow" || saveOverride) {
                throw e;
            }
            return false;
        }
    }

    /**
     * Tab-close save path. Uses the record's ``urgentSave()`` (sendBeacon
     * under the hood), bypassing the model mutex and normal RPC pipeline.
     * Surfaces ``onUrgentSaveFailed`` when sendBeacon can't deliver the
     * payload (e.g. it exceeds the browser's sendBeacon budget).
     *
     * @returns {Promise<boolean>} whether the urgent save succeeded
     */
    async requestUrgentSave() {
        if (this.isSaving) {
            // Re-entrant: a save is already in flight and owns the epoch, so
            // this call must not claim a terminal (it would settle a state it
            // does not own). It must still surface its own failure the same way
            // the main path does — previously a throw here left ``status`` on
            // "saving" forever (``isSaving`` drives FormStatusIndicator's
            // spinner) while ``lastError`` stayed null and
            // ``onUrgentSaveFailed`` never ran, so a tab closed during an
            // in-flight save reported a permanently pending save it had
            // actually abandoned.
            try {
                const succeeded = await this.model.root.urgentSave();
                if (!succeeded) {
                    this.hooks.onUrgentSaveFailed?.();
                }
                return succeeded;
            } catch (e) {
                this.lastError = e;
                this.hooks.onUrgentSaveFailed?.();
                throw e;
            }
        }
        this._transition("begin");
        const ownerEpoch = ++this._saveEpoch;
        try {
            const succeeded = await this.model.root.urgentSave();
            if (succeeded) {
                this._finishTransition("ok", ownerEpoch);
            } else {
                if (ownerEpoch === this._saveEpoch) {
                    this.hooks.onUrgentSaveFailed?.();
                }
                this._finishTransition("failed", ownerEpoch);
            }
            return succeeded;
        } catch (e) {
            this._finishTransition("failed", ownerEpoch);
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = e;
            }
            throw e;
        }
    }

    /**
     * Discard pending changes and return to a clean state. Claims the epoch
     * (like a save) so the discard is ordered against concurrent saves in
     * both directions: a save already in flight finishes as a no-op instead
     * of racing the ``discard`` transition, and a save started while
     * ``root.discard()`` is pending (e.g. a slow onchange queued behind the
     * model mutex) supersedes the discard — applying ``discard`` after that
     * save's ``begin`` would settle ``saving → clean`` under its feet,
     * turning its own terminal into an invalid transition from ``clean``.
     */
    async requestDiscard() {
        const ownerEpoch = ++this._saveEpoch;
        await this.model.root.discard();
        if (ownerEpoch !== this._saveEpoch) {
            return;
        }
        this._transition("discard");
        this.lastError = null;
    }

    /**
     * Build the ``onError`` callback passed to ``record.save()``, based on
     * the requested error UX mode:
     *
     *   - ``dialog``  — render ``FormErrorDialog`` (via ``hooks.onSaveError``)
     *                   with discard / redirect / stay choices. Multi-company
     *                   recovery runs first and may shortcut to ``retry()``.
     *                   Errors without a server payload (no ``error.data`` —
     *                   e.g. ``ConnectionLostError``) can't feed the dialog
     *                   and are rethrown instead; ``requestSave``'s catch
     *                   settles them as ``failed``.
     *   - ``rethrow`` — propagate to the caller's try/catch. Matches the
     *                   historical ``onSaveError(error, opts, false)``
     *                   semantics.
     *   - ``silent``  — pass no onError. ``record.save()`` rethrows
     *                   internally, the coordinator's catch swallows it and
     *                   returns false. Used for fire-and-forget auto-save
     *                   (tab-switch).
     *
     * @param {"dialog"|"rethrow"|"silent"} errorMode
     * @returns {((error: any, callbacks: any) => any) | undefined}
     */
    _buildOnError(errorMode, ownerEpoch) {
        if (errorMode === "silent") {
            return undefined;
        }
        if (errorMode === "rethrow") {
            return async (error, callbacks) => {
                if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                    return callbacks.retry();
                }
                throw error;
            };
        }
        return async (error, callbacks) => {
            if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                return callbacks.retry();
            }
            if (!error?.data) {
                throw error;
            }
            if (ownerEpoch !== this._saveEpoch) {
                return false;
            }
            this.lastError = error;
            return await this.hooks.onSaveError(error, callbacks);
        };
    }
}
