// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_save_coordinator - Centralizes the form view's save lifecycle as observable state */

/**
 * Owns the form's save lifecycle as observable reactive state.
 *
 * Replaces the historical pattern where ``form_controller.js`` exposed
 * 9 distinct save-related entry points (``onPagerUpdate``,
 * ``beforeVisibilityChange``, ``beforeLeave``, ``beforeUnload``,
 * ``shouldExecuteAction``, ``beforeExecuteActionButton``, ``create``,
 * ``save``, ``saveButtonClicked``) and each one independently:
 *
 *   1. Read ``model.root.isDirty()`` (or skipped the check).
 *   2. Built its own ``{ onError, reload, nextId, ... }`` argument bag.
 *   3. Decided between ``record.save()`` and ``props.saveRecord(...)``.
 *   4. Routed errors through ``onSaveError(error, opts, showErrorDialog)``
 *      with a positional boolean whose meaning had drifted across
 *      callers (the rename in 2026-05 documented the drift but didn't
 *      eliminate it).
 *
 * Today every entry point in the controller is a ~3-line method that
 * calls ``coordinator.requestSave({...})`` with named options.  The
 * coordinator does the dispatch + status tracking + error routing.
 *
 * The status field is the single observable surface for external readers
 * instead of each one reverse-engineering state from ``record.dirty`` +
 * scattered ``isSaving`` flags.  Current consumer: ``FormStatusIndicator``
 * (subscribes via ``useState`` and derives its saving / post-error display
 * states from ``status``); it remains open for dialog blockers and route
 * guards.
 *
 * Out-of-contract callers: code that invokes ``model.root.save()`` /
 * ``root.discard()`` directly (several field widgets, e.g.
 * ``@web/fields/translation_button``, and assorted addon widgets) bypasses
 * the coordinator entirely — ``status`` will not reflect those saves.
 * New form-level save paths must go through ``requestSave`` /
 * ``requestDiscard`` / ``requestUrgentSave``.
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
 * Allowed status transitions, keyed by source state.  ``_transition``
 * looks up ``TRANSITIONS[status]?.[event]``; ``undefined`` means the
 * event is not declared valid from the current state and the coordinator
 * throws ``InvalidFormSaveTransitionError`` instead of silently corrupting
 * status.
 *
 * Notable non-obvious cells:
 *   - ``saving → begin → saving``: concurrent ``requestSave`` re-entry
 *     under the mutex; status is already ``"saving"`` so this is a
 *     no-op assignment that the guard must permit.
 *   - ``error → begin → saving``: retry path after an unhandled
 *     exception.  No explicit reset is required.
 *
 * The omitted cells (e.g. ``ok`` from ``clean``) catch programming
 * errors: routing a save-completion outcome without ever entering
 * ``saving``.
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

    /** @type {any | null} Last unhandled error, surfaced for diagnostics. */
    lastError = null;

    /**
     * Monotonic counter incremented on every ``begin`` (new save in flight)
     * and on every discard (in-flight saves invalidated by a discard).
     * Each save — and each discard — captures its own ``_saveEpoch`` on
     * entry; its settlement (``ok`` / ``recoverable`` / ``failed`` for
     * saves, ``discard`` for discards) is silently dropped when the
     * current epoch has moved on, because the state has already been
     * settled by a concurrent save or discard.  This is the only
     * legitimate source of stale terminals — misrouted outcomes from
     * outside ``requestSave`` / ``requestUrgentSave`` still surface as
     * ``InvalidFormSaveTransitionError``.
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
     * Apply a status transition with a guard.  Throws
     * ``InvalidFormSaveTransitionError`` if ``event`` is not declared
     * valid from the current state in ``TRANSITIONS``.  Every status
     * write inside this class must go through here so latent
     * misroutings (e.g. a ``failed`` outcome when no save was in flight)
     * surface immediately instead of corrupting downstream observers.
     *
     * External direct writes to ``this.status`` (e.g. from tests
     * forcing a starting state) bypass the guard by design.
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
     * Terminal-event helper.  Routes ``ok`` / ``recoverable`` / ``failed``
     * through ``_transition`` only when ``ownerEpoch`` is still the current
     * ``_saveEpoch``.  Concurrent saves and mid-save discards bump the
     * epoch, so the losing save's terminal becomes a no-op instead of
     * either throwing or corrupting the now-settled status.
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
     * Save the form record.  All save-related entry points in
     * ``form_controller.js`` (and ``settings_form_controller.js``) route
     * through here.  Note: field widgets that call ``model.root.save()``
     * directly are out-of-contract — ``status`` / ``isSaving`` do not
     * reflect those saves (see the module docstring).
     *
     * Resolves to:
     *   - ``true`` on a successful save (or ``checkDirty`` short-circuit)
     *   - ``false`` when the save was blocked, validation failed, or the
     *     dialog UX returned "stay here"
     *   - the saveOverride / record.save return value when those return
     *     a non-boolean (e.g. an action descriptor)
     *
     * Throws when ``errorMode === "rethrow"`` and ``record.save()`` raises.
     * Other modes ("dialog", "silent") capture the error in ``lastError``
     * and return false.
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
            // Nothing to save — the caller's pre-flight returned clean.
            return true;
        }
        this.lastError = null;
        this._transition("begin");
        // Claim an epoch *after* the begin transition so a concurrent
        // requestSave can supersede this one (saving → begin → saving is
        // permitted as a no-op; the new save bumps the epoch and inherits
        // ownership of the outcome).
        const ownerEpoch = ++this._saveEpoch;
        const opts = { reload, ...params };
        if (nextId !== undefined) {
            opts.nextId = nextId;
        }
        try {
            let saved;
            if (saveOverride) {
                // Embedder-supplied save (``props.saveRecord``) owns its
                // own error handling.  Don't inject the coordinator's
                // onError callback — the embedder may not understand the
                // dialog/recovery contract and could route errors through
                // an unintended UX path.
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
            // ``saved === false`` means validation failed pre-RPC, or the
            // dialog UX (errorMode=dialog) returned "stay here" — both are
            // recoverable states where the record stays dirty for the user
            // to address.  Not "error", which is reserved for unhandled
            // throws.
            this._finishTransition("recoverable", ownerEpoch);
            return false;
        } catch (e) {
            this._finishTransition("failed", ownerEpoch);
            // ``lastError`` is observable state; only the owning save
            // should overwrite it (a stale failure shouldn't poison a
            // successor save's clean diagnostics).
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = e;
            }
            if (errorMode === "rethrow") {
                throw e;
            }
            // silent: swallow, controller decides whether to surface.
            return false;
        }
    }

    /**
     * Tab-close save path.  Uses the record's ``urgentSave()`` (sendBeacon
     * under the hood) which bypasses the model mutex and the normal RPC
     * pipeline.  Surfaces the ``onUrgentSaveFailed`` hook when sendBeacon
     * cannot deliver the payload (e.g. it's larger than the browser's
     * sendBeacon budget).
     *
     * @returns {Promise<boolean>} whether the urgent save succeeded
     */
    async requestUrgentSave() {
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
     * Discard pending changes and return to a clean state.  Claims the
     * epoch (like a save) so the discard is ordered against concurrent
     * saves in both directions:
     *
     *   - a save already in flight when the discard starts finishes as a
     *     no-op — its terminal would otherwise race the ``discard``
     *     transition;
     *   - a save started while ``root.discard()`` is pending (queued
     *     behind the model mutex, e.g. a slow onchange) supersedes the
     *     discard: applying ``discard`` after that save's ``begin`` would
     *     settle ``saving → clean`` under the save's feet, turning its
     *     own terminal into an invalid transition from ``clean``.
     */
    async requestDiscard() {
        const ownerEpoch = ++this._saveEpoch;
        await this.model.root.discard();
        if (ownerEpoch !== this._saveEpoch) {
            // A newer save (or discard) claimed the epoch while
            // ``root.discard()`` was pending — it owns the settlement.
            return;
        }
        this._transition("discard");
        this.lastError = null;
    }

    /**
     * Build the ``onError`` callback to pass into ``record.save()`` based
     * on the requested error UX mode.
     *
     *   - ``dialog``  — render ``FormErrorDialog`` (via ``hooks.onSaveError``)
     *                   with discard / redirect / stay choices.  The
     *                   multi-company recovery pre-check runs first and
     *                   may shortcut to ``retry()``.  Errors without a
     *                   server payload (no ``error.data`` — e.g.
     *                   ``ConnectionLostError``) cannot feed the dialog
     *                   and are rethrown instead; ``requestSave``'s catch
     *                   settles them as ``failed`` and resolves false.
     *   - ``rethrow`` — propagate the error to the caller's try/catch by
     *                   re-throwing inside the onError callback.  Matches
     *                   the historical ``onSaveError(error, opts, false)``
     *                   path semantically: ``record.save()`` returns
     *                   nothing (it throws), the coordinator's catch sets
     *                   ``status=error`` and re-throws.
     *   - ``silent``  — pass no onError.  ``record.save()`` re-throws
     *                   internally, the coordinator's catch swallows it
     *                   and returns false.  Used for fire-and-forget
     *                   auto-save paths (tab-switch).
     *
     * @param {"dialog"|"rethrow"|"silent"} errorMode
     * @returns {((error: any, callbacks: any) => any) | undefined}
     */
    _buildOnError(errorMode, ownerEpoch) {
        if (errorMode === "silent") {
            return undefined;
        }
        if (errorMode === "rethrow") {
            // Recovery still runs first — ``rethrow`` means "if the error
            // survives recovery, bubble it up to the caller (e.g.
            // ``saveButtonClicked``) instead of rendering FormErrorDialog".
            // Without the recovery branch here, the legacy
            // ``record.save({onError})`` semantic (which ran
            // ``onSaveError`` on every save, including the recoverable
            // multi-company AccessError) is lost: AccessError with
            // ``suggested_company`` rethrows instead of triggering the
            // company-switch retry, breaking multi-company UX.
            return async (error, callbacks) => {
                if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                    return callbacks.retry();
                }
                throw error;
            };
        }
        // dialog mode (default)
        return async (error, callbacks) => {
            if (this.hooks.recoverFromSaveError?.(error, this.model)) {
                // Recovery is transparent — the original error never
                // surfaced to the user.  Don't touch ``lastError`` so
                // a successful retry leaves the coordinator clean and
                // downstream consumers (``shouldExecuteAction`` etc.)
                // see the eventual success.
                return callbacks.retry();
            }
            if (!error?.data) {
                // ``FormErrorDialog`` requires a server-provided payload
                // (``props.data`` / ``props.message``).  Non-RPC failures
                // (``ConnectionLostError``, timeouts, programming errors)
                // carry none: rendering the dialog would TypeError on
                // ``error.data.message`` and mask the original failure.
                // Rethrow instead — ``requestSave``'s catch records the
                // error, settles status to "error" and resolves false, so
                // the caller (e.g. breadcrumb navigation) cleanly blocks.
                throw error;
            }
            // Recovery failed → dialog UX runs.  Record the error in
            // ``lastError`` so it survives even when the dialog
            // resolves it via "discard": the action menu's
            // ``shouldExecuteAction`` blocks menu actions on any
            // dialog-shown error, matching historical semantics.
            // Epoch-guarded like the catch-path writes: a superseded save's
            // late onError must not poison a successor's clean diagnostics
            // ("clean" status with a stale lastError blocks menu actions).
            if (ownerEpoch === this._saveEpoch) {
                this.lastError = error;
            }
            return await this.hooks.onSaveError(error, callbacks);
        };
    }
}
