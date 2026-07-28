// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_service - Action manager that routes server/client actions to views, dialogs, and URL redirects */

import { reactive } from "@odoo/owl";
import { router as _router } from "@web/core/browser/router";
import { AppEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { actionLog } from "@web/core/utils/asset_log";
import { Deferred, KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { View, ViewNotFoundError } from "@web/views/view";

import { executeActionButton } from "./action_button_executor.js";
import { installActionCacheInvalidation } from "./action_cache_invalidation.js";
import { clearUncommittedChanges } from "./action_clear_changes.js";
import {
    ControllerNotFoundError,
    DIALOG_SIZES,
    standardActionServiceProps,
} from "./action_constants.js";
import { ActionDialog } from "./action_dialog.js";
import { ActionDispatch } from "./action_dispatch.js";
import {
    executeActURLAction,
    openActionInNewWindow,
    openURL,
} from "./action_executors/act_url.js";
import { executeActWindowAction } from "./action_executors/act_window.js";
import { executeClientAction } from "./action_executors/client.js";
import { executeCloseAction } from "./action_executors/close.js";
import { executeServerAction } from "./action_executors/server.js";
import { buildActionInfo, buildViewInfo } from "./action_info_builders.js";
import { loadAction, makeController, preprocessAction } from "./action_loader.js";
import { getActionParams, makeActionState } from "./action_state.js";
import { actionStorage } from "./action_storage.js";
import { BreadcrumbCache } from "./breadcrumb_cache.js";
import { buildBreadcrumbs, controllersFromState } from "./breadcrumb_manager.js";
import { makeControllerComponent } from "./controller_component.js";
import { loadState } from "./load_state.js";
import { executeReportAction } from "./reports/report_executor.js";
import { SkeletonView } from "./skeleton_view.js";

const actionHandlersRegistry = registry.category("action_handlers");
const actionRegistry = registry.category("actions");

actionRegistry.addValidation((entry) => typeof entry === "function");

actionHandlersRegistry.addValidation((entry) => typeof entry === "function");

/**
 * The router surface the action layer actually consumes — deliberately NOT
 * ``typeof router``.
 *
 * ``makeActionManager(env, router)`` is public: ``web_studio``'s editor
 * (``enterprise/web_studio/.../editor.js``) passes a hand-built stub with
 * exactly these four members, because Studio's manager must not touch the real
 * URL. Typing the parameter as the concrete ``router`` singleton would reject
 * that legitimate caller and overstate the dependency; these four are the whole
 * contract (verified 2026-07-25 — the only ``router.*`` accesses anywhere in
 * ``webclient/actions/`` are ``current``, ``pushState``, ``stateToUrl`` and the
 * one ``hideKeyFromUrl`` call in the constructor).
 *
 * @typedef {Object} RouterLike
 * @property {Object} current the current parsed URL state
 * @property {(state: Object, options?: Object) => void} pushState
 * @property {(state: Object) => string} stateToUrl
 * @property {(key: string) => void} hideKeyFromUrl
 */

/** @typedef {number|false} ActionId */
/** @typedef {Object} ActionDescription */
/** @typedef {"current" | "fullscreen" | "new" | "main" | "self"} ActionMode */
/** @typedef {string} ActionTag */
/** @typedef {string} ActionXMLId */
/** @typedef {Object} Context */
/** @typedef {Function} CallableFunction */
/** @typedef {string} ViewType */

/** @typedef {ActionId|ActionXMLId|ActionTag|ActionDescription} ActionRequest */

/** @typedef {Object} Action */
/** @typedef {Action & { type: "ir.actions.act_window" }} ActWindowAction */
/** @typedef {Action & { type: "ir.actions.act_url" }} ActURLAction */
/** @typedef {Action & { type: "ir.actions.client" }} ClientAction */
/** @typedef {Action & { type: "ir.actions.server" }} ServerAction */
/** @typedef {Action & { type: "ir.actions.report" }} ReportAction */
/** @typedef {Object} Controller */
/** @typedef {Object} BaseView */
/** @typedef {Object} ActionProps */
/** @typedef {Object} Config */
/** @typedef {Object} UpdateStackOptions */
/** @typedef {Object} DoActionButtonParams */

/**
 * @typedef {Object} ActionOptions
 * @property {Context} [additionalContext]
 * @property {boolean} [clearBreadcrumbs]
 * @property {CallableFunction} [onClose]
 * @property {Object} [props]
 * @property {ViewType} [viewType]
 * @property {"replaceCurrentAction" | "replacePreviousAction"} [stackPosition]
 * @property {number} [index]
 * @property {boolean} [newWindow]
 * @property {boolean} [forceLeave]
 * @property {Object[]} [newStack]
 * @property {boolean} [noEmptyTransition]
 * @property {Function} [onActionReady]
 * @property {number} [_actionDepth] internal — guards against runaway action chaining (see _executeAction)
 */

export { clearUncommittedChanges };

export { ControllerNotFoundError, standardActionServiceProps };

/**
 * Combine the ``onClose`` a replaced dialog handed over with the one the
 * replacing action brought of its own.
 *
 * A ``target="new"`` action opened while a dialog is already up REPLACES it, so
 * the outgoing dialog never "closed" as far as its opener is concerned: its
 * callback is stolen, re-armed on the replacement, and fires when the chain
 * finally closes. Both callbacks run, innermost first — the order the dialogs
 * would have unwound in had they closed one at a time.
 *
 * The two belong to DIFFERENT actions, so neither may cancel the other: each
 * leg runs in its own try and failures are re-raised afterwards. Dropping one
 * silently is not a lesser failure — ``doAction(..., { onClose: resolve })`` is
 * how the calendar controller and the view-button confirmation flow AWAIT a
 * dialog, so a skipped callback is an ``await`` that never returns.
 *
 * Neither callback is wrapped when the other is absent, keeping the identity of
 * the common single-callback path and the "no onClose at all" fast path.
 *
 * @param {Function} [own] the replacing action's own ``options.onClose``
 * @param {Function} [stolen] the callback carried over from the dialog being replaced
 * @returns {Function|undefined}
 */
function chainOnClose(own, stolen) {
    if (!own) {
        return stolen;
    }
    if (!stolen) {
        return own;
    }
    return async (closeParams) => {
        const errors = [];
        for (const onClose of [own, stolen]) {
            try {
                await onClose(closeParams);
            } catch (error) {
                errors.push(error);
            }
        }
        if (errors.length === 1) {
            throw errors[0];
        }
        if (errors.length) {
            throw new AggregateError(errors, "Several onClose callbacks failed");
        }
    };
}

/**
 * THE SIBLING CONTRACT
 * ====================
 *
 * The modules this file delegates to (``action_executors/*``,
 * ``breadcrumb_manager``, ``load_state``, ``action_button_executor``,
 * ``controller_component``, ``reports/report_executor``, ``action_loader``,
 * ``action_info_builders``, ``action_cache_invalidation``) all take the
 * ActionManager INSTANCE as their last parameter. That is deliberate and must
 * not be narrowed to the collaborators each one happens to need today:
 *
 *  - ``enterprise/web_studio/.../editor.js`` does ``Object.assign(action,
 *    { doAction })``, and siblings call ``am.doAction()`` LATE-BOUND. Capturing
 *    ``doAction`` at construction time would silently break Studio's
 *    interception.
 *  - ``_loadAction`` / ``_executeCloseAction`` / ``_getBreadcrumbs`` are used as
 *    test seams via fake ``am`` object literals.
 *
 * The sanctioned surface is enumerated in ``sibling_contract.test.js``, which
 * asserts it in both directions: every listed member must still exist, and the
 * manager must expose nothing beyond it. Adding a member is therefore a change
 * to that list, not to a comment here — a prose copy would only drift out of
 * step with the assertion that enforces it.
 *
 * Only three sites WRITE manager state, and each is documented where it happens:
 *   ``action_dispatch.js``       controllerStack (commit on mount / roll back on
 *                                error), dialog + nextDialog (the two-slot
 *                                commit — see ``_removeDialog``). This is the
 *                                per-dispatch transaction object;
 *                                ``ControllerComponent`` only reports which
 *                                outcome its lifecycle observed.
 *   ``action_cache_invalidation.js``  breadcrumbCache (flush by replacement —
 *                                see the NOTE in breadcrumb_cache.js)
 *   ``load_state.js``            _loadStateGeneration (navigation intent)
 *
 * Anything not on the sanctioned list is private to this file.
 *
 * Action manager — routes ``doAction`` / button clicks / URL state changes
 * to the appropriate action executor, maintains the breadcrumb controller
 * stack, manages the dialog overlay, and synchronizes URL state.
 *
 * ``makeActionManager(env, router)`` remains the public entry point:
 * ``enterprise/web_studio/.../editor.js`` calls it and uses the result as an
 * action-manager surface.
 */
export class ActionManager {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {RouterLike} [router]
     */
    constructor(env, router = _router) {
        this.env = env;
        this.router = router;
        this.breadcrumbCache = new BreadcrumbCache();
        this.keepLast = new KeepLast({ rejectSuperseded: true });
        /** Monotonic id source — feeds controller_<n>/action_<n> stamps and ACTION_MANAGER:UPDATE event ids. */
        this._id = 0;
        this.controllerStack = [];
        this.dialog = null;
        this.nextDialog = null;
        this._skeletonDef = null;
        this._loadStateGeneration = 0;

        router.hideKeyFromUrl("globalState");

        this.uninstallActionCacheInvalidation = () => {};

        /** @type {Record<string, (action: Object, options: ActionOptions) => Promise<any> | void>} */
        this._actionExecutors = {
            "ir.actions.act_url": (a, o) => executeActURLAction(a, o, this),
            "ir.actions.act_window": (a, o) => executeActWindowAction(a, o, this),
            "ir.actions.act_window_close": (a, o) => this._executeCloseAction(a, o),
            "ir.actions.client": (a, o) => executeClientAction(a, o, this),
            "ir.actions.server": (a, o) => executeServerAction(a, o, this),
            "ir.actions.report": (a, o) => executeReportAction(a, o, this),
        };

        this.ControllerComponent = makeControllerComponent(this);
    }

    async _controllersFromState(state) {
        return controllersFromState(state, this);
    }

    /**
     * Removes the current dialog from the action service's state.
     *
     * Invariant: ``this.dialog`` is cleared *before* the user-provided
     * ``onClose`` runs, so re-entrant calls (e.g. an inline follow-up's
     * ``dialog.closeAll()``) find it already null and ``onClose`` fires once.
     *
     * DOM removal happens *after* ``onClose`` resolves, so a button-action
     * ``onClose`` that reloads the view keeps the dialog visible until the
     * reload completes — matching the cancel path and the "wait for view
     * reload before closing" regression tests.
     *
     * When ``removeFn`` is given (the dialog-service ``onClose`` closures
     * built in ``_dispatchTargetNew`` pass their own remove function), the
     * teardown only runs if the closing entry is the *committed* one:
     * discarding a pending, never-mounted replacement must not tear down the
     * still-visible committed dialog.
     *
     * @param {any} [closeParams]
     * @param {Function} [removeFn] identity of the closing dialog's remove
     * @return {Promise<void>}
     */
    async _removeDialog(closeParams, removeFn) {
        if (removeFn && this.nextDialog && this.nextDialog.remove === removeFn) {
            if (this.dialog && !this.dialog.onClose) {
                this.dialog.onClose = this.nextDialog.stolenOnClose;
            }
            this.nextDialog = null;
            return;
        }
        const dialog = this.dialog;
        if (!dialog || (removeFn && removeFn !== dialog.remove)) {
            return;
        }
        const { onClose, remove } = dialog;
        this.dialog = null;
        try {
            await onClose?.(closeParams);
        } finally {
            remove();
        }
    }

    /**
     * Returns the last controller of the current controller stack.
     *
     * @returns {Controller|null}
     */
    _getCurrentController() {
        const stack = this.controllerStack;
        return stack.length ? stack.at(-1) : null;
    }

    /**
     * Returns the current action, which is the action of the last controller in the stack.
     *
     * @returns {Promise<any>}
     */
    async _getCurrentAction() {
        const currentController = this._getCurrentController();
        let action = null;
        if (currentController) {
            if (currentController.virtual) {
                try {
                    action = await this._loadAction(currentController.action.id);
                } catch (error) {
                    if (
                        error.exceptionName ===
                        "odoo.addons.web.controllers.action.MissingActionError"
                    ) {
                        action = null;
                    } else {
                        throw error;
                    }
                }
            } else {
                action = JSON.parse(currentController.action._originalAction || "null");
            }
        }
        return action;
    }

    /**
     * Allocate the next monotonic id (feeds controller_<n>/action_<n> stamps
     * and ACTION_MANAGER:UPDATE ids). Encapsulates ``++this._id`` so sibling
     * modules don't reach into the private slot directly.
     *
     * @returns {number} the post-increment value
     */
    _nextId() {
        return ++this._id;
    }

    /**
     * Snapshot the current navigation generation. Every ``doAction`` /
     * ``switchView`` / ``restore`` bumps ``keepLast._id`` when it enters the
     * KeepLast, so a later increment means a newer navigation started. Callers
     * that ``await`` something long OUTSIDE the KeepLast (notably
     * ``clearUncommittedChanges``, which can block on a save dialog) snapshot
     * this before the await and compare after via {@link _isSupersededNav} to
     * avoid mounting a stale controller on top of a newer one.
     *
     * @returns {number}
     */
    _navGeneration() {
        return this.keepLast.generation;
    }

    /**
     * @param {number} generation a value previously returned by
     *   {@link _navGeneration}
     * @returns {boolean} true if a newer navigation has started since
     */
    _isSupersededNav(generation) {
        return this.keepLast.generation !== generation;
    }

    /**
     * Ask every mounted controller for permission to leave, then re-check that
     * no newer navigation started while we waited.
     *
     * Both halves are mandatory and must stay together.
     * ``clearUncommittedChanges`` can block indefinitely (a save dialog
     * awaiting the user) and it awaits OUTSIDE the KeepLast, so the KeepLast
     * cannot arbitrate that window: the caller must snapshot the navigation
     * generation before the await and re-check it after. Centralising both
     * here means a new transition path cannot add the consent await and forget
     * the re-check — the failure mode being a stale controller mounting on top
     * of a newer one (see the ``concurrency.test.js`` suite, which covers this
     * for each of the four entry points).
     *
     * Internal — also called by sibling ``action_executors/*`` with the
     * ActionManager instance as ``this``. No ``@private`` tag: TS reads it as
     * strict class-private and would block sibling-module access.
     *
     * @param {{ forceLeave?: boolean }} [options]
     * @returns {Promise<boolean>} ``true`` if the caller may proceed
     */
    async _confirmLeave(options = {}) {
        const navGeneration = this._navGeneration();
        const canProceed = await clearUncommittedChanges(this.env, options);
        return canProceed && !this._isSupersededNav(navGeneration);
    }

    async _loadAction(actionRequest, context = {}) {
        return loadAction(actionRequest, context);
    }

    _makeController(params) {
        return makeController(params, this);
    }

    _preprocessAction(action, context = {}) {
        return preprocessAction(action, context, this);
    }

    /**
     * Internal — called by sibling ``action_executors/*`` and
     * ``action_info_builders.js`` with the ActionManager instance as
     * ``this``. No ``@private`` tag: TS reads it as strict class-private
     * and would block sibling-module access.
     * "The current action has no such view" and "the current action is not a
     * window action at all" are the SAME answer to this question — ``null`` —
     * and the callers already handle it: ``switchView`` raises a typed
     * ``ViewNotFoundError``, and ``openFormView`` falls through to opening a
     * standalone form via ``doAction``.
     *
     * Answering the second case with a throw instead would make the outcome
     * depend on WHY the view is unavailable, and that case is reachable:
     * ``openFormView`` is captured as the ``selectRecord`` / ``createRecord``
     * prop of a view controller, and ``list_controller.openRecord`` awaits
     * ``record.isDirty()`` and ``record.save()`` before calling it — so a
     * navigation landing inside that window leaves a client action on the stack
     * tip, and a row click must degrade to the form rather than to an error
     * dialog.
     *
     * @param {string} viewType
     * @throws {ControllerNotFoundError} if there is no current controller
     * @returns {any} the view descriptor, or ``null`` when the current action
     *   cannot provide it
     */
    _getView(viewType) {
        const currentController = this.controllerStack.at(-1);
        if (!currentController) {
            // Not reachable from any in-tree caller today — every one of them
            // runs from a mounted controller — but this is public service API,
            // and the typed error names the problem where the next line would
            // only raise a bare TypeError.
            throw new ControllerNotFoundError(
                `Cannot resolve view '${viewType}': the controller stack is empty`,
            );
        }
        if (currentController.action.type !== "ir.actions.act_window") {
            return null;
        }
        const view = currentController.views.find((view) => view.type === viewType);
        return view || null;
    }

    _getBreadcrumbs(stack) {
        return buildBreadcrumbs(stack, this);
    }

    /**
     * Reconstruct an action request from URL state.
     * Delegates to the extracted getActionParams in action_state.
     */
    _getActionParams(state) {
        return getActionParams(state);
    }

    /**
     * @param {ClientAction} action
     * @param {Object} props
     * @returns {{ props: ActionProps, config: Config }}
     */
    _getActionInfo(action, props) {
        return buildActionInfo(action, props, this);
    }

    /**
     * @param {BaseView} view
     * @param {ActWindowAction} action
     * @param {BaseView[]} views
     * @param {Object} props
     */
    _getViewInfo(view, action, views, props = {}) {
        return buildViewInfo(view, action, views, props, this);
    }

    /** @returns {string|undefined} jsId of the action owning the top controller */
    _topActionJsId() {
        return this.controllerStack.at(-1)?.action.jsId;
    }

    /**
     * @returns {string|undefined} jsId of the action below the top one, or
     *   ``undefined`` when the stack holds a single action
     */
    _previousActionJsId() {
        const topJsId = this._topActionJsId();
        for (let i = this.controllerStack.length - 1; i >= 0; i--) {
            const jsId = this.controllerStack[i].action.jsId;
            if (jsId !== topJsId) {
                return jsId;
            }
        }
        return undefined;
    }

    /**
     * Computes the position of the controller in the nextStack according to options
     * @param {ActionOptions} options
     */
    _computeStackIndex(options) {
        if (options.clearBreadcrumbs) {
            return 0;
        } else if (options.stackPosition === "replaceCurrentAction") {
            const currentController = this.controllerStack.at(-1);
            if (currentController) {
                return this.controllerStack.findIndex(
                    (ct) => ct.action.jsId === currentController.action.jsId,
                );
            }
        } else if (options.stackPosition === "replacePreviousAction") {
            // Walk back past every controller of the TOP action (an action can
            // own several — one per view type it was switched through) and land
            // on the first controller of the one before it. When the whole
            // stack is a single action there is no previous one, so index 0
            // replaces it — the same degradation the previous spelling had.
            const target = this._previousActionJsId() ?? this._topActionJsId();
            if (target) {
                return this.controllerStack.findIndex(
                    (ct) => ct.action.jsId === target,
                );
            }
        } else if (options.index !== undefined) {
            return options.index;
        }
        return this.controllerStack.length;
    }

    /**
     * Triggers a re-rendering with respect to the given controller.
     *
     * Thin orchestrator: builds the {@link ActionDispatch} transaction (which
     * owns the outer promise and the commit/fail/discard transitions the
     * eventual ``ControllerComponent`` triggers), early-exits for
     * ``newWindow``, wires
     * the controller's reactive config via {@link _prepareControllerConfig},
     * then dispatches to:
     *
     *  - {@link _dispatchTargetNew} for ``action.target === "new"``
     *    (renders the controller inside an ActionDialog).
     *  - {@link _dispatchInline} otherwise (drives ACTION_MANAGER:UPDATE
     *    so the action_container swaps in the new controller).
     *
     * Internal — called by sibling ``action_executors/*`` and
     * ``reports/report_executor.js`` with the ActionManager instance as
     * ``this``. No ``@private`` tag: TS reads it as strict class-private.
     *
     * @param {Controller} controller
     * @param {Object} [options]
     * @param {boolean} [options.clearBreadcrumbs]
     * @param {number} [options.index]
     * @param {any[]} [options.newStack]
     * @param {boolean} [options.newWindow]
     * @param {Function} [options.onClose]
     * @param {boolean} [options.noEmptyTransition]
     * @param {Function} [options.onActionReady]
     * @param {boolean} [options.isBreadcrumbRestore] this dispatch is a
     *   user-initiated breadcrumb click, so the URL still points at the
     *   CURRENTLY-DISPLAYED controller (``pushState`` only runs on mount). If
     *   the restored controller then errors before mounting, roll back to that
     *   displayed stack rather than to the truncated ``newStack`` tip, making
     *   the failed click a no-op and keeping the URL consistent. A ``loadState``
     *   dispatch runs AFTER the browser already changed the URL and must
     *   degrade within that URL's stack, so it deliberately does NOT set this.
     *   Read here, consumed by ``ControllerComponent``'s ``onError`` via
     *   ``ActionDispatch``'s ``restoreStackOnError``.
     * @returns {Promise<any>}
     */
    async _updateUI(controller, options = {}) {
        const action = controller.action;
        const previousStack = this.controllerStack;
        if (action.target !== "new" && options.newStack) {
            this.controllerStack = options.newStack;
        }
        const index = this._computeStackIndex(options);
        const nextStack = [...this.controllerStack.slice(0, index), controller];
        const dispatch = new ActionDispatch(this, {
            controller,
            action,
            nextStack,
            restoreStackOnError: options.isBreadcrumbRestore
                ? previousStack
                : undefined,
        });
        if (action.target !== "new" && options.newWindow) {
            return this._openActionInNewWindow(action, makeActionState(nextStack));
        }
        this._prepareControllerConfig(controller, action, nextStack);

        if (action.target === "new") {
            return this._dispatchTargetNew(dispatch, options);
        }
        return this._dispatchInline(dispatch, options);
    }

    /**
     * Wires the controller's reactive ``config`` slots that drive UI
     * affordances (breadcrumbs, display name, history back, reloading
     * flag).
     *
     * Pure side effects on ``controller.config`` — no return value,
     * no bus events, no dialog interactions. Lives outside the dispatch
     * branches because BOTH ``_dispatchTargetNew`` and
     * ``_dispatchInline`` need the same config plumbing.
     *
     * @param {Controller} controller
     * @param {any} action
     * @param {Controller[]} nextStack
     */
    _prepareControllerConfig(controller, action, nextStack) {
        controller.config.breadcrumbs = reactive(
            action.target === "new" ? [] : this._getBreadcrumbs(nextStack),
        );
        controller.config.getDisplayName = () => controller.displayName;
        controller.config.setDisplayName = (displayName) => {
            controller.displayName = displayName;
            if (controller === this._getCurrentController()) {
                // eslint-disable-next-line no-restricted-syntax -- service-internal code: useService is component-only, and `title` is a declared dependency (started before us)
                this.env.services.title.setParts({ action: controller.displayName });
            }
            if (action.target !== "new") {
                const crumb = controller.config.breadcrumbs.find(
                    (bc) => bc.jsId === controller.jsId,
                );
                if (crumb) {
                    crumb.name = displayName;
                }
            }
        };
        controller.config.historyBack = () => {
            const previousController =
                this.controllerStack[this.controllerStack.length - 2];
            if (previousController) {
                this.restore(previousController.jsId);
            } else {
                this.env.bus.trigger(AppEvent.WEBCLIENT_LOAD_DEFAULT_APP);
            }
        };
        controller.config.isReloadingController =
            controller === this.controllerStack.at(-1);
    }

    /**
     * Dispatch path for ``action.target === "new"``: renders the
     * controller inside an ActionDialog registered on the dialog
     * service. Replaces any prior ``nextDialog`` so only one
     * action-as-dialog is live at a time.
     *
     * Returns the dispatch's promise so callers see the same resolution timing
     * as the inline path — it settles when the ControllerComponent mounts and
     * the dispatch commits.
     *
     * @param {ActionDispatch} dispatch the transaction for this dispatch
     * @param {Object} options the original ``_updateUI`` options
     * @returns {Promise<any>}
     */
    _dispatchTargetNew(dispatch, options) {
        const { controller, action, removeDialogRef } = dispatch;
        const actionDialogProps = {
            ActionComponent: this.ControllerComponent,
            actionProps: { ...controller.props, _context: dispatch },
            actionType: action.type,
        };
        if (action.name) {
            actionDialogProps.title = action.name;
        }
        const size = DIALOG_SIZES[action.context.dialog_size];
        if (size) {
            actionDialogProps.size = size;
        }
        actionDialogProps.header = action.context.header ?? actionDialogProps.header;
        actionDialogProps.footer = action.context.footer ?? actionDialogProps.footer;
        const stolenOnClose = this.nextDialog?.stolenOnClose ?? this.dialog?.onClose;
        delete this.dialog?.onClose;
        // eslint-disable-next-line no-restricted-syntax -- service-internal code: useService is component-only, and `dialog` is a declared dependency (started before us)
        const removeDialogFn = (removeDialogRef.current = this.env.services.dialog.add(
            ActionDialog,
            actionDialogProps,
            {
                onClose: (closeParams) =>
                    this._removeDialog(closeParams, removeDialogFn),
            },
        ));
        if (this.nextDialog) {
            const superseded = this.nextDialog;
            this.nextDialog = null;
            superseded.remove();
        }
        this.nextDialog = {
            remove: removeDialogFn,
            onClose: chainOnClose(options.onClose, stolenOnClose),
            // The PURE stolen callback, never the chained one: ``_removeDialog``
            // hands this back to the committed dialog when this pending entry is
            // discarded without ever mounting, and in that case this action's own
            // ``onClose`` must NOT come along — nothing of it ever opened.
            stolenOnClose,
        };
        return dispatch.settled();
    }

    /**
     * Dispatch path for the default case (``action.target`` is not
     * ``"new"``): captures the outgoing controller's local/global
     * state, optionally injects a SkeletonView during full breadcrumb
     * clear, then triggers ACTION_MANAGER:UPDATE so the
     * action_container swaps in the new controller.
     *
     * @param {ActionDispatch} dispatch the transaction for this dispatch
     * @param {Object} options the original ``_updateUI`` options
     * @returns {Promise<void>}
     */
    async _dispatchInline(dispatch, options) {
        const { controller, action } = dispatch;
        if (this._skeletonDef) {
            this._skeletonDef.reject(new SupersededError());
            this._skeletonDef = null;
        }
        const currentController = this._getCurrentController();
        if (currentController?.getLocalState) {
            currentController.exportedState = currentController.getLocalState();
        }
        if (controller.exportedState) {
            controller.props.state = controller.exportedState;
        }

        if (currentController?.getGlobalState) {
            const globalState = Object.assign(
                {},
                currentController.action.globalState,
                currentController.getGlobalState(),
            );

            currentController.action.globalState = globalState;
            if (
                currentController.state.action === this.router.current.action &&
                currentController.state.active_id === this.router.current.active_id &&
                currentController.state.resId === this.router.current.resId
            ) {
                this.router.pushState({ globalState }, { sync: true });
            }
        }
        if (controller.action.globalState) {
            controller.props.globalState = controller.action.globalState;
        }

        if (options.clearBreadcrumbs && !options.noEmptyTransition) {
            const def = (this._skeletonDef = new Deferred());
            const isActWindow = action.type === "ir.actions.act_window";
            this.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {
                id: this._nextId(),
                Component: SkeletonView,
                componentProps: {
                    onMounted: () => def.resolve(),
                    viewType: isActWindow ? controller.props.type : undefined,
                    withControlPanel: isActWindow,
                },
            });
            try {
                await def;
            } catch (error) {
                if (!(error instanceof SupersededError)) {
                    throw error;
                }
                return;
            } finally {
                if (this._skeletonDef === def) {
                    this._skeletonDef = null;
                }
            }
        }
        if (options.onActionReady) {
            options.onActionReady(action);
        }
        controller.__info__ = {
            id: this._nextId(),
            Component: this.ControllerComponent,
            componentProps: { ...controller.props, _context: dispatch },
        };
        // eslint-disable-next-line no-restricted-syntax -- service-internal code: useService is component-only, and `dialog` is a declared dependency (started before us)
        this.env.services.dialog.closeAll({ noReload: true });
        this.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, controller.__info__);
        await dispatch.settled();
    }

    _openURL(url) {
        return openURL(url, this);
    }

    _openActionInNewWindow(action, state) {
        return openActionInNewWindow(action, state, this);
    }

    _executeCloseAction(action = {}, options = {}) {
        return executeCloseAction(this, action, options);
    }

    /**
     * Main entry point of a 'doAction' request. Loads the action and executes it.
     *
     * @param {ActionRequest} actionRequest
     * @param {ActionOptions} options
     * @returns {Promise<number | undefined | void>}
     */
    async doAction(actionRequest, options = {}) {
        actionLog("doAction", actionRequest, options);
        options = { ...options };
        const actionProm = this._loadAction(actionRequest, options.additionalContext);
        let action = await this.keepLast.add(actionProm);
        action = this._preprocessAction(action, options.additionalContext);
        options.clearBreadcrumbs = action.target === "main" || options.clearBreadcrumbs;

        if (Object.hasOwn(this._actionExecutors, action.type)) {
            actionLog("dispatch", action.type, action.id || action.tag || "");
            return this._actionExecutors[action.type](action, options);
        }
        const handler = actionHandlersRegistry.get(action.type, undefined);
        if (handler !== undefined) {
            actionLog("handler", action.type);
            return handler({ env: this.env, action, options });
        }
        throw new Error(
            `The ActionManager service can't handle actions of type ${action.type}`,
        );
    }

    /**
     * Executes an action on top of the current one (typically, when a button in a
     * view is clicked). Delegates to the extracted executeActionButton.
     *
     * @param {DoActionButtonParams} params
     * @param {Object} [options={}]
     * @returns {Promise<void>}
     */
    async doActionButton(params, options) {
        return executeActionButton(this, params, options);
    }

    /**
     * Switches to the given view type in action of the last controller of the
     * stack. This action must be of type 'ir.actions.act_window'.
     *
     * @param {ViewType} viewType
     * @param {Object} [props={}]
     * @params {Object} [options={}]
     * @params {boolean} [options.newWindow] set to true to open the action in a new tab/window.
     * @throws {ViewNotFoundError} if the viewType is not found on the current action
     * @returns {Promise<Number>}
     */
    /**
     * @param {string} viewType
     * @param {Object} [props={}]
     * @param {{ newWindow?: boolean }} [options={}]
     */
    async switchView(viewType, props = {}, { newWindow } = {}) {
        await this.keepLast.add(Promise.resolve());
        if (this.dialog) {
            return;
        }
        const controller = this.controllerStack.at(-1);
        const view = this._getView(viewType);
        if (!view) {
            throw new ViewNotFoundError(
                _t(
                    "No view of type '%s' could be found in the current action.",
                    viewType,
                ),
            );
        }
        const newController =
            controller.action.controllers[viewType] ||
            this._makeController({
                Component: View,
                action: controller.action,
                views: controller.views,
                view,
            });

        if (!newWindow && !(await this._confirmLeave())) {
            return;
        }

        Object.assign(
            newController,
            this._getViewInfo(view, controller.action, controller.views, props),
        );
        controller.action.controllers[viewType] = newController;
        let index;
        if (view.multiRecord) {
            index = this.controllerStack.findIndex(
                (ct) => ct.action.jsId === controller.action.jsId,
            );
            index = index > -1 ? index : this.controllerStack.length - 1;
        } else {
            index = this.controllerStack.findIndex(
                (ct) =>
                    ct.action.jsId === controller.action.jsId &&
                    !ct.virtual &&
                    !ct.view.multiRecord,
            );
            index = index > -1 ? index : this.controllerStack.length;
        }
        return this._updateUI(newController, { newWindow, index });
    }

    /**
     * Restores a controller from the controller stack given its id. Typically,
     * this function is called when clicking on the breadcrumbs. If no id is given
     * restores the previous controller from the stack (penultimate).
     *
     * @param {string} jsId
     */
    async restore(jsId) {
        await this.keepLast.add(Promise.resolve());
        let index;
        if (!jsId) {
            index = this.controllerStack.length - 2;
        } else {
            index = this.controllerStack.findIndex(
                (controller) => controller.jsId === jsId,
            );
        }
        if (index < 0) {
            const msg = jsId
                ? "Invalid controller to restore"
                : "No controller to restore";
            throw new ControllerNotFoundError(msg);
        }
        if (!(await this._confirmLeave())) {
            return;
        }
        const controller = this.controllerStack[index];
        if (controller.virtual) {
            const actionParams = this._getActionParams(controller.state);
            if (!actionParams) {
                throw new Error(
                    "Attempted to restore a virtual controller whose state is invalid",
                );
            }
            const { actionRequest, options } = actionParams;
            return this.doAction(actionRequest, {
                ...options,
                newStack: this.controllerStack.slice(0, index),
                isBreadcrumbRestore: true,
            });
        }
        if (controller.action.type === "ir.actions.act_window") {
            if (controller.isMounted) {
                controller.exportedState = controller.getLocalState();
            }
            const { action, exportedState, view, views } = controller;
            const props = { ...controller.props };
            if (exportedState && "resId" in exportedState) {
                props.resId = exportedState.resId;
            }
            Object.assign(controller, this._getViewInfo(view, action, views, props));
        }
        return this._updateUI(controller, { index, isBreadcrumbRestore: true });
    }

    async loadState(state) {
        return loadState(this, state);
    }

    async loadAction(actionRequest, context) {
        const action = await this._loadAction(actionRequest, context);
        return this._preprocessAction(action, context);
    }

    pushState(cStack = this.controllerStack, options) {
        if (!cStack.length) {
            return;
        }

        const newState = makeActionState(cStack);
        actionStorage.setCurrentState(newState);

        cStack.at(-1).state = newState;
        this.router.pushState(newState, Object.assign({ replace: true }, options));
    }

    get currentController() {
        return this._getCurrentController();
    }

    get currentAction() {
        return this._getCurrentAction();
    }
}

/**
 * Thin factory preserved for back-compat.  External consumers
 * (``enterprise/web_studio/.../editor.js``) call this with ``(env, router)``
 * and use the return as an action-manager surface — the
 * {@link ActionManager} instance fulfills that surface.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {RouterLike} [router]
 * @returns {ActionManager}
 */
export function makeActionManager(env, router = _router) {
    return new ActionManager(env, router);
}

export const actionService = {
    dependencies: ["dialog", "effect", "localization", "notification", "title", "ui"],
    start(env) {
        const am = makeActionManager(env);
        am.uninstallActionCacheInvalidation = installActionCacheInvalidation(am);
        return am;
    },
};

registry.category("services").add("action", actionService);
