// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_service - Action manager that routes server/client actions to views, dialogs, and URL redirects */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router as _router } from "@web/core/browser/router";
import { AppEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { actionLog } from "@web/core/utils/asset_log";
import { Deferred, KeepLast } from "@web/core/utils/concurrency";
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
import { buildBreadcrumbs, controllersFromState } from "./breadcrumb_manager.js";
import { makeControllerComponent } from "./controller_component.js";
import { loadState } from "./load_state.js";
import { executeReportAction } from "./reports/report_executor.js";
import { SkeletonView } from "./skeleton_view.js";

// ``BlankComponent`` moved to ``controller_component.js`` along with the
// ``ControllerComponent`` class that consumes it.  No external consumers.

const actionHandlersRegistry = registry.category("action_handlers");
const actionRegistry = registry.category("actions");

// Client actions are either an OWL Component (rendered in the controller
// stack) or a plain function run for side-effects that may return an action
// descriptor to chain. Both are `typeof === "function"`.
actionRegistry.addValidation((entry) => typeof entry === "function");

// Server-action handlers keyed by `action.type` (e.g.
// "ir_actions_account_report_download"). Each is a function called with
// `({ action, options, env })` to execute outside the standard client flow.
actionHandlersRegistry.addValidation((entry) => typeof entry === "function");

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

// ``clearUncommittedChanges`` moved to ``action_clear_changes.js`` to avoid
// a circular import; re-exported here to preserve the historical import
// path for external consumers (known: window_action.test.js).
export { clearUncommittedChanges };

// -----------------------------------------------------------------------------
// ActionManager (Service)
// -----------------------------------------------------------------------------

// ``standardActionServiceProps`` and ``ControllerNotFoundError`` moved to
// ``action_constants.js`` so the module's pure-data declarations group
// together. Re-exported below to preserve the historical import path.
export { ControllerNotFoundError, standardActionServiceProps };

// ``ControllerComponentTemplate`` moved to ``controller_component.js``
// where it's consumed by the ControllerComponent class.

/**
 * Action manager — routes ``doAction`` / button clicks / URL state changes
 * to the appropriate action executor, maintains the breadcrumb controller
 * stack, manages the dialog overlay, and synchronizes URL state.
 *
 * Lifted from a closure-based factory to a class in 2026-05; kept API-
 * compatible because external consumers (``enterprise/web_studio/.../editor.js``)
 * still call ``makeActionManager(env, router)`` expecting the same method shape.
 */
export class ActionManager {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("@web/core/browser/router").Router} [router]
     */
    constructor(env, router = _router) {
        // -------------------------------------------------------------------
        // State (was closure locals in the legacy factory)
        // -------------------------------------------------------------------
        this.env = env;
        this.router = router;
        this.breadcrumbCache = {};
        // rejectSuperseded: a doAction/switchView/restore superseded by a
        // newer navigation rejects its awaiter with a SupersededError (swallowed
        // by the error service) instead of hanging forever. This is what makes
        // supersession observable — awaiters use plain try/finally rather than
        // the bespoke escape hatches the never-settling wrapper used to force.
        this.keepLast = new KeepLast({ rejectSuperseded: true });
        /** Monotonic id source — feeds controller_<n>/action_<n> stamps and ACTION_MANAGER:UPDATE event ids. */
        this._id = 0;
        this.controllerStack = [];
        this.dialog = null;
        this.nextDialog = null;

        router.hideKeyFromUrl("globalState");

        // The RPC cache-invalidation listener (a permanent rpcBus RPC:RESPONSE
        // subscription) is NOT installed here: installing it in the ctor made
        // every ``makeActionManager`` caller leak a listener that pins the whole
        // manager for the page's lifetime. Short-lived managers (e.g.
        // enterprise/web_studio's editor) were the only such callers and never
        // disposed it. Install is now the consumer's responsibility:
        // ``actionService.start`` installs it for the session-lived webclient
        // manager (never disposed — fine), and web_studio's editor installs it
        // and disposes on teardown (``onWillDestroy``). Default to a no-op so
        // ``uninstallActionCacheInvalidation()`` is always safe to call.
        this.uninstallActionCacheInvalidation = () => {};

        // -------------------------------------------------------------------
        // Action-type dispatcher
        // -------------------------------------------------------------------
        // Sibling modules (``action_executors/*``, ``breadcrumb_manager``,
        // ``load_state``, ``action_button_executor``, ``controller_component``,
        // ``reports/report_executor``, ``action_loader``,
        // ``action_info_builders``) take the ActionManager instance directly
        // as their last parameter — no curated ctx object — mirroring the
        // closure-let semantics the pre-class factory provided.
        //
        // ``clearUncommittedChanges`` lives in ``action_clear_changes.js``
        // (not on the class) so executor modules can import it without a
        // circular dependency on this module.

        /** @type {Record<string, (action: Object, options: ActionOptions) => Promise>} */
        this._actionExecutors = {
            "ir.actions.act_url": (a, o) => this._executeActURLAction(a, o),
            "ir.actions.act_window": (a, o) => this._executeActWindowAction(a, o),
            "ir.actions.act_window_close": (a, o) => this._executeCloseAction(a, o),
            "ir.actions.client": (a, o) => this._executeClientAction(a, o),
            "ir.actions.server": (a, o) => this._executeServerAction(a, o),
            "ir.actions.report": (a, o) => this._executeReportAction(a, o),
        };

        // Called once per ActionManager lifetime so the returned class
        // identity stays stable across renders (OWL's reconciler patches
        // instead of remounting). The only sibling module that *writes*
        // this manager's state (committing the stack on mount, swapping
        // ``dialog``↔``nextDialog``); every other module only reads.
        this.ControllerComponent = makeControllerComponent(this);
    }

    // ---------------------------------------------------------------------------
    // misc
    // ---------------------------------------------------------------------------

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
                action = JSON.parse(currentController.action._originalAction);
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
        return this.keepLast._id;
    }

    /**
     * @param {number} generation a value previously returned by
     *   {@link _navGeneration}
     * @returns {boolean} true if a newer navigation has started since
     */
    _isSupersededNav(generation) {
        return this.keepLast._id !== generation;
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
     * @param {string} viewType
     * @throws {Error} if the current controller is not a view
     * @returns {any}
     */
    _getView(viewType) {
        const currentController = this.controllerStack.at(-1);
        if (currentController.action.type !== "ir.actions.act_window") {
            throw new Error(
                `switchView called but the current controller isn't a view`,
            );
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
            let last;
            for (let i = this.controllerStack.length - 1; i >= 0; i--) {
                const action = this.controllerStack[i].action.jsId;
                if (!last) {
                    last = action;
                }
                if (action !== last) {
                    last = action;
                    break;
                }
            }
            if (last) {
                return this.controllerStack.findIndex((ct) => ct.action.jsId === last);
            }
            // TODO: throw if there is no previous action?
        } else if (options.index !== undefined) {
            return options.index;
        }
        return this.controllerStack.length;
    }

    /**
     * Triggers a re-rendering with respect to the given controller.
     *
     * Thin orchestrator: builds the shared ``controllerContext`` (carries
     * the outer Promise's ``resolve``/``reject`` to the eventual
     * ``ControllerComponent`` mount), early-exits for ``newWindow``, wires
     * the controller's reactive config via {@link _prepareControllerConfig},
     * then dispatches to:
     *
     *  - {@link _dispatchTargetNew} for ``action.target === "new"``
     *    (renders the controller inside an ActionDialog).
     *  - {@link _dispatchInline} otherwise (drives ACTION_MANAGER:UPDATE
     *    so the action_container swaps in the new controller).
     *
     * The historical "DAM Remarks" TODO on globalState handling survives
     * in ``_dispatchInline`` where it semantically belongs.
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
     * @returns {Promise<any>}
     */
    async _updateUI(controller, options = {}) {
        let resolve;
        let reject;
        const currentActionProm = new Promise((_res, _rej) => {
            resolve = _res;
            reject = _rej;
        });
        const action = controller.action;
        // Snapshot the displayed stack BEFORE the (load-bearing) early commit of
        // ``newStack``: the early commit makes the parent breadcrumb the current
        // action while the new controller initializes, but if this dispatch is a
        // breadcrumb restore that then errors before mounting, ``onError`` uses
        // this snapshot to return to the displayed controller (see restore()).
        const previousStack = this.controllerStack;
        if (action.target !== "new" && "newStack" in options) {
            this.controllerStack = options.newStack;
        }
        const index = this._computeStackIndex(options);
        const nextStack = [...this.controllerStack.slice(0, index), controller];
        const removeDialogRef = { current: undefined };
        const controllerContext = {
            controller,
            action,
            nextStack,
            resolve,
            reject,
            removeDialogRef,
            // Only breadcrumb restores set this; loadState deliberately does not
            // (it must degrade within the already-committed URL's stack).
            restoreStackOnError: options.isBreadcrumbRestore
                ? previousStack
                : undefined,
        };
        if (action.target !== "new" && options.newWindow) {
            return this._openActionInNewWindow(action, makeActionState(nextStack));
        }
        this._prepareControllerConfig(controller, action, nextStack);

        if (action.target === "new") {
            return this._dispatchTargetNew(
                controllerContext,
                options,
                currentActionProm,
            );
        }
        return this._dispatchInline(controllerContext, options, currentActionProm);
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
                // if not mounted yet, will be done in "mounted"
                this.env.services.title.setParts({ action: controller.displayName });
            }
            if (action.target !== "new") {
                // The crumb's `name` is a plain slot on the reactive
                // breadcrumbs array: writing it through the array notifies
                // exactly the subscribers that read this crumb's name.
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
     * Returns the outer ``currentActionProm`` so callers see the same
     * resolution timing as the inline path — the promise resolves when
     * the ControllerComponent mounts and invokes ``_context.resolve()``.
     *
     * @param {Object} controllerContext shared dispatch context
     * @param {Object} options the original ``_updateUI`` options
     * @param {Promise<any>} currentActionProm outer promise to return
     * @returns {Promise<any>}
     */
    _dispatchTargetNew(controllerContext, options, currentActionProm) {
        const { controller, action, removeDialogRef } = controllerContext;
        const actionDialogProps = {
            ActionComponent: this.ControllerComponent,
            actionProps: { ...controller.props, _context: controllerContext },
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
        // Propagate the committed dialog's onClose through the replacement
        // chain: the callback transfers to the entry built below (a pending
        // replacement may already carry it as ``stolenOnClose``), and
        // deleting it here guarantees the old dialog's removal (performed by
        // ControllerComponent.onMounted once the new dialog is mounted)
        // fires no user callback.
        const onClose = this.nextDialog?.stolenOnClose ?? this.dialog?.onClose;
        delete this.dialog?.onClose;
        const removeDialogFn = (removeDialogRef.current = this.env.services.dialog.add(
            ActionDialog,
            actionDialogProps,
            {
                onClose: (closeParams) =>
                    this._removeDialog(closeParams, removeDialogFn),
            },
        ));
        if (this.nextDialog) {
            // Discard a dialog that was dispatched but never mounted (its
            // ControllerComponent has not committed it to ``this.dialog``
            // yet). _removeDialog's identity guard keeps the committed
            // dialog alive, and the discarded entry's stolen onClose already
            // transferred above.
            this.nextDialog.remove();
        }
        this.nextDialog = {
            remove: removeDialogFn,
            onClose: onClose || options.onClose,
            // Tracked separately so a failed/discarded replacement can hand
            // the committed dialog's callback back (see onError) instead of
            // silently dropping it with the discarded entry.
            stolenOnClose: onClose,
        };
        return currentActionProm;
    }

    /**
     * Dispatch path for the default case (``action.target`` is not
     * ``"new"``): captures the outgoing controller's local/global
     * state, optionally injects a SkeletonView during full breadcrumb
     * clear, then triggers ACTION_MANAGER:UPDATE so the
     * action_container swaps in the new controller.
     *
     * The ``"TODO DAM Remarks"`` block survives here — it's a long-
     * standing open question about globalState's value for client
     * actions. Resolution would require a separate audit of every
     * ``getGlobalState`` implementer; outside the scope of this
     * mechanical extraction.
     *
     * @param {Object} controllerContext shared dispatch context
     * @param {Object} options the original ``_updateUI`` options
     * @param {Promise<any>} currentActionProm outer promise to await
     * @returns {Promise<void>}
     */
    async _dispatchInline(controllerContext, options, currentActionProm) {
        const { controller, action } = controllerContext;
        const currentController = this._getCurrentController();
        if (currentController?.getLocalState) {
            currentController.exportedState = currentController.getLocalState();
        }
        if (controller.exportedState) {
            controller.props.state = controller.exportedState;
        }

        // TODO DAM Remarks:
        // this thing seems useless for client actions.
        // restore and switchView (at least) use this --> cannot be done in switchView only
        // if prop globalState has been passed in doAction, since the action is new the prop won't be overridden in l655.
        // if globalState is not useful for client actions --> maybe use that thing in useSetupView instead of useSetupAction?
        // a good thing: the Object.assign seems to reflect the use of "externalState" in legacy Model class --> things should be fine.
        if (currentController?.getGlobalState) {
            const globalState = Object.assign(
                {},
                currentController.action.globalState,
                currentController.getGlobalState(), // what if this = {}?
            );

            currentController.action.globalState = globalState;
            // Avoid pushing the globalState, if the state on the router was changed.
            // For instance, if a link was clicked, the state of the router will be the one of the link and not the one of the currentController.
            // Or when using the back or forward buttons on the browser.
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
            const def = new Deferred();
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
            await def;
        }
        if (options.onActionReady) {
            options.onActionReady(action);
        }
        controller.__info__ = {
            id: this._nextId(),
            Component: this.ControllerComponent,
            componentProps: { ...controller.props, _context: controllerContext },
        };
        this.env.services.dialog.closeAll({ noReload: true });
        this.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, controller.__info__);
        await currentActionProm;
    }

    // ---------------------------------------------------------------------------
    // ir.actions.act_url
    // ---------------------------------------------------------------------------

    _openURL(url) {
        return openURL(url, this);
    }

    _openActionInNewWindow(action, state) {
        return openActionInNewWindow(action, state, this);
    }

    _executeActURLAction(action, options) {
        return executeActURLAction(action, options, this);
    }

    // ---------------------------------------------------------------------------
    // ir.actions.act_window
    // ---------------------------------------------------------------------------

    async _executeActWindowAction(action, options) {
        return executeActWindowAction(action, options, this);
    }

    // ---------------------------------------------------------------------------
    // ir.actions.client
    // ---------------------------------------------------------------------------

    async _executeClientAction(action, options) {
        return executeClientAction(action, options, this);
    }

    // ---------------------------------------------------------------------------
    // ir.actions.report
    // ---------------------------------------------------------------------------

    _executeReportAction(action, options) {
        return executeReportAction(action, options, this);
    }

    // ---------------------------------------------------------------------------
    // ir.actions.server
    // ---------------------------------------------------------------------------

    async _executeServerAction(action, options) {
        return executeServerAction(action, options, this);
    }

    _executeCloseAction(action = {}, options = {}) {
        return executeCloseAction(this, action, options);
    }

    // ---------------------------------------------------------------------------
    // public API
    // ---------------------------------------------------------------------------

    /**
     * Main entry point of a 'doAction' request. Loads the action and executes it.
     *
     * @param {ActionRequest} actionRequest
     * @param {ActionOptions} options
     * @returns {Promise<number | undefined | void>}
     */
    async doAction(actionRequest, options = {}) {
        actionLog("doAction", actionRequest, options);
        // Shallow-copy: options is caller-owned and possibly reused across
        // calls; the executors (and the clearBreadcrumbs default below)
        // must not mutate it in place.
        options = { ...options };
        const actionProm = this._loadAction(actionRequest, options.additionalContext);
        let action = await this.keepLast.add(actionProm);
        action = this._preprocessAction(action, options.additionalContext);
        options.clearBreadcrumbs = action.target === "main" || options.clearBreadcrumbs;

        if (Object.hasOwn(this._actionExecutors, action.type)) {
            actionLog("dispatch", action.type, action.id || action.tag || "");
            return this._actionExecutors[action.type](action, options);
        }
        const handler = actionHandlersRegistry.get(action.type, null);
        if (handler !== null) {
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
            // we don't want to switch view when there's a dialog open, as we would
            // not switch in the correct action (action in background != dialog action)
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

        if (!newWindow) {
            const navGeneration = this._navGeneration();
            const canProceed = await clearUncommittedChanges(this.env);
            if (!canProceed) {
                return;
            }
            if (this._isSupersededNav(navGeneration)) {
                // A newer doAction/switchView/restore started while the save
                // dialog was up; abort so this stale switch can't mount over it.
                return;
            }
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
            // This case would mostly happen when loadState detects a change in the URL.
            // Also, I guess we may need it when we have other monoRecord views
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
        const navGeneration = this._navGeneration();
        const canProceed = await clearUncommittedChanges(this.env);
        if (!canProceed) {
            return;
        }
        if (this._isSupersededNav(navGeneration)) {
            // A newer navigation started while the save dialog was up; abort so
            // this stale restore can't mount over it.
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
            // Don't pre-truncate the live stack: if doAction rejects (e.g. a
            // MissingActionError for a deleted action reached via breadcrumb),
            // the currently-displayed controller must remain committed. Hand
            // the truncated stack to _updateUI via the existing `newStack`
            // plumbing, which only commits it once the action has loaded.
            //
            // ``isBreadcrumbRestore``: this is a user-initiated breadcrumb
            // click, so the URL still points at the currently-displayed
            // controller (pushState only runs on mount). If the restored view
            // then errors BEFORE mounting, we must return to that displayed
            // controller — NOT the truncated newStack tip — so the failed click
            // is a no-op and the URL stays consistent. (A loadState dispatch,
            // by contrast, runs AFTER the browser changed the URL and must
            // degrade within that URL's stack, so it does NOT set this flag.)
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
                // Use the last exported ID of the controller when restoring
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
        browser.sessionStorage.setItem("current_state", JSON.stringify(newState));

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
 * @param {import("@web/core/browser/router").Router} [router]
 * @returns {ActionManager}
 */
export function makeActionManager(env, router = _router) {
    return new ActionManager(env, router);
}

export const actionService = {
    dependencies: ["dialog", "effect", "localization", "notification", "title", "ui"],
    start(env) {
        const am = makeActionManager(env);
        // Install the RPC cache-invalidation listener here (not in the
        // ActionManager ctor) so ONLY the session-lived webclient manager
        // installs the permanent rpcBus RPC:RESPONSE listener. It lives for the
        // whole page, so it is never disposed — no leak. Short-lived managers
        // built directly via ``makeActionManager`` (web_studio's editor) opt in
        // explicitly and dispose on teardown. See the ctor note.
        am.uninstallActionCacheInvalidation = installActionCacheInvalidation(am);
        return am;
    },
};

registry.category("services").add("action", actionService);
