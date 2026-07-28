// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_dispatch - The commit/fail/discard transaction behind a single _updateUI dispatch */

import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";

import { actionStorage } from "./action_storage.js";
import { getActionMode } from "./action_views.js";
import { BlankComponent } from "./blank_component.js";

const actionRegistry = registry.category("actions");

/** @import { ActionManager } from "./action_service.js" */

/**
 * ONE ``_updateUI`` DISPATCH, AS A TRANSACTION.
 * =============================================
 *
 * A dispatch proposes a change to action-manager state and only applies it if
 * the controller actually reaches the DOM. It has exactly three outcomes:
 *
 *   {@link commit}   the controller mounted        -> swap in ``nextStack``, or
 *                                                     promote the pending dialog
 *   {@link fail}     it errored before mounting    -> roll back to a good stack,
 *                                                     or tear the pending dialog
 *                                                     down (which hands the
 *                                                     stolen ``onClose`` back)
 *   {@link discard}  a newer dispatch destroyed it -> settle the awaiter so it
 *                    before it could mount            cannot hang
 *
 * WHY THIS EXISTS
 * ---------------
 * These three outcomes used to live in ``ControllerComponent``'s lifecycle
 * hooks, while the matching *proposals* (``nextStack``, ``nextDialog``) were
 * made in ``action_service``. One transaction, opened in one file and closed in
 * another, with no object in between — so its invariants could only be stated
 * as prose. Notably this one, which is now {@link _releasePendingDialog}:
 *
 *   "Any future path that tears a pending dialog down WITHOUT going through its
 *    remove() must clear the slot itself."
 *
 * The component keeps what is genuinely component-local (OWL's ``status``, the
 * ``CallbackRecorder``s) and passes it in; everything that mutates the manager
 * lives here.
 *
 * NOT a general-purpose abstraction: one instance per dispatch, used once.
 */
export class ActionDispatch {
    /**
     * @param {ActionManager} am
     * @param {Object} params
     * @param {Object} params.controller
     * @param {Object} params.action
     * @param {Object[]} params.nextStack the stack to commit on mount
     * @param {Object[]} [params.restoreStackOnError] set only by a breadcrumb
     *   restore: the stack that is currently DISPLAYED. The URL still points at
     *   it (``pushState`` only runs on mount), so a restore that errors before
     *   mounting must return here rather than to the truncated ``nextStack``
     *   tip, making the failed click a no-op. ``loadState`` deliberately does
     *   not set it — it runs after the browser already changed the URL and must
     *   degrade within that URL's stack.
     */
    constructor(am, { controller, action, nextStack, restoreStackOnError }) {
        this.am = am;
        this.controller = controller;
        this.action = action;
        this.nextStack = nextStack;
        this.restoreStackOnError = restoreStackOnError;
        /**
         * Identity of the dialog this dispatch registered, set by
         * ``_dispatchTargetNew``. A ref rather than a plain field because the
         * dialog service hands the remove function back only after the entry
         * exists, and the failure path needs it later.
         * @type {{ current?: Function }}
         */
        this.removeDialogRef = { current: undefined };
        /**
         * Settled by exactly one of commit/fail/discard. ``_updateUI`` returns
         * it, so every ``doAction`` awaiter is waiting on this.
         * @type {Promise<any>}
         */
        this.promise = new Promise((resolve, reject) => {
            this._resolve = resolve;
            this._reject = reject;
        });
    }

    /**
     * The controller mounted: apply the proposal.
     *
     * @param {Object} exporters state exporters owned by the component — they
     *   close over its ``CallbackRecorder``s, so they cannot be built here
     * @param {() => any} exporters.getGlobalState
     * @param {() => any} exporters.getLocalState
     */
    commit({ getGlobalState, getLocalState }) {
        const { am, controller, action, nextStack } = this;
        if (action.target === "new") {
            this._commitDialog();
        } else {
            controller.getGlobalState = getGlobalState;
            controller.getLocalState = getLocalState;
            am.controllerStack = nextStack;
            am.pushState();

            am.env.services.title.setParts({ action: controller.displayName });
            actionStorage.setCurrentAction(action._originalAction);
            actionStorage.setLang(user.lang);
        }
        controller.isMounted = true;
        this._resolve();
        am.env.bus.trigger(
            AppEvent.ACTION_MANAGER_UI_UPDATED,
            getActionMode(action, actionRegistry),
        );
    }

    /**
     * Promote the pending dialog over the committed one.
     *
     * The removal chain synchronously nulls ``am.dialog`` and fires no user
     * callback, because ``_dispatchTargetNew`` already moved ``onClose`` onto
     * ``am.nextDialog``. Clearing the pending slot afterwards keeps the two
     * from ever aliasing.
     */
    _commitDialog() {
        const { am } = this;
        am.dialog?.remove();
        am.dialog = am.nextDialog;
        am.nextDialog = null;
    }

    /**
     * The dispatch outcome as a dispatch path must expose it to its caller:
     * supersession is a quiet resolve, every other failure propagates.
     *
     * Both paths go through here, because the "quiet resolve" half of
     * {@link discard}'s contract lives in the awaiter, not in the rejection.
     * ``_dispatchTargetNew`` used to return {@link promise} raw while
     * ``_dispatchInline`` swallowed the SupersededError itself, so a dialog
     * dispatch superseded before it mounted rejected into its ``doAction``
     * caller — an unhandled rejection whenever that caller did not await, which
     * this contract says cannot happen.
     *
     * @returns {Promise<any>}
     */
    async settled() {
        try {
            return await this.promise;
        } catch (error) {
            if (!(error instanceof SupersededError)) {
                throw error;
            }
        }
    }

    /**
     * A newer ``ACTION_MANAGER:UPDATE`` destroyed this controller before it
     * mounted, so neither commit nor fail will run. Settle the awaiter or every
     * ``doAction`` caller of the superseded action hangs forever.
     *
     * {@link settled} is what turns this rejection into the quiet resolve
     * callers observe; it never reaches the global error service.
     *
     * @param {{ componentStatus: string }} ctx OWL's ``status(component)``
     */
    discard({ componentStatus }) {
        if (!this.controller.isMounted && componentStatus !== "mounted") {
            this._reject(new SupersededError());
        }
    }

    /**
     * The controller threw. Surface the error and leave the action container in
     * an unbroken state.
     *
     * @param {Error} error
     * @param {{ componentStatus: string }} ctx OWL's ``status(component)``
     * @returns {any} a recovery promise when one is started
     */
    fail(error, { componentStatus }) {
        const { am, controller, action } = this;
        if (controller.isMounted) {
            Promise.reject(error);
            return;
        }
        if (componentStatus === "mounted") {
            this._reject(new SupersededError());
            am.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {
                id: am._nextId(),
                Component: BlankComponent,
                componentProps: {
                    onMounted: () => {},
                    withControlPanel: action.type === "ir.actions.act_window",
                },
            });
            Promise.reject(error);
            return;
        }
        this._reject(error);
        if (action.target === "new") {
            return this._releasePendingDialog();
        }
        return this._restoreStack();
    }

    /**
     * Tear down a dialog that failed before mounting.
     *
     * INVARIANT — SINGLE OWNER. ``remove()`` runs
     * ``overlay.remove -> dialog onRemove -> options.onClose ->
     * am._removeDialog(closeParams, removeFn)`` SYNCHRONOUSLY, and
     * ``_removeDialog``'s identity guard is the one place that recognises "the
     * dialog going away is the PENDING one": it hands ``stolenOnClose`` back to
     * the committed dialog and clears the slot.
     *
     * A duplicate of that recovery used to sit here and was proven unreachable
     * (``_removeDialog`` had always nulled ``nextDialog`` by the time it ran).
     * Keep the recovery there. Any future path that tears a pending dialog down
     * WITHOUT going through its ``remove()`` must clear the slot itself.
     */
    _releasePendingDialog() {
        this.removeDialogRef.current?.();
    }

    /**
     * Return the controller stack to a state the user can act on.
     *
     * @returns {any} the restore promise, when one is started
     */
    _restoreStack() {
        const { am, controller } = this;
        const index = am.controllerStack.findIndex((ct) => ct.jsId === controller.jsId);
        if (index > 0) {
            return am.restore(am.controllerStack[index - 1].jsId);
        }
        if (index === 0) {
            return;
        }
        const { restoreStackOnError } = this;
        if (
            restoreStackOnError?.length &&
            restoreStackOnError.at(-1).isMounted &&
            am.controllerStack !== restoreStackOnError
        ) {
            am.controllerStack = restoreStackOnError;
        }
        const lastController = am.controllerStack.at(-1);
        if (!lastController) {
            am.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {});
            return;
        }
        if (lastController.jsId !== controller.jsId) {
            return am.restore(lastController.jsId);
        }
    }
}
