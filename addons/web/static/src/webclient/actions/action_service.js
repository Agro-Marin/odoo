// @ts-check
/** @odoo-module native */

import { reactive } from "@odoo/owl";
import { router as _router } from "@web/core/browser/router";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { actionLog } from "@web/core/utils/asset_log";
import { omit } from "@web/core/utils/collections/objects";
import { Deferred, SupersededError } from "@web/core/utils/concurrency";
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
import { NavigationTracker } from "./navigation_token.js";
import { executeReportAction } from "./reports/report_executor.js";
import { SkeletonView } from "./skeleton_view.js";

const actionHandlersRegistry = registry.category("action_handlers");
const actionRegistry = registry.category("actions");

actionRegistry.addValidation((entry) => typeof entry === "function");

actionHandlersRegistry.addValidation((entry) => typeof entry === "function");

/**
 * @typedef {Object} RouterLike
 * @property {Object} current
 * @property {(state: Object, options?: Object) => void} pushState
 * @property {(state: Object) => string} stateToUrl
 * @property {(key: string) => void} hideKeyFromUrl
 */

/** @typedef {number|false} ActionId */
/** @typedef {Object} ActionDescription */
/** @typedef {"current" | "fullscreen" | "new" | "main" | "self"} ActionMode */
/** @typedef {string} ActionTag */
/** @typedef {string} ActionXMLId */
/** @typedef {Record<string, any>} Context */
/** @typedef {Function} CallableFunction */
/** @typedef {string} ViewType */

/** @typedef {ActionId|ActionXMLId|ActionTag|ActionDescription} ActionRequest */

/**
 * @typedef {Object} Action
 * @property {string} type
 * @property {ActionId} [id]
 * @property {string} [xml_id]
 * @property {string} [path]
 * @property {string} [name]
 * @property {string} [display_name]
 * @property {ActionMode|"download"} [target]
 * @property {Context} [context]
 * @property {any[]|string} [domain]
 * @property {string} [res_model]
 * @property {number|false} [res_id]
 * @property {any[][]} [views]
 * @property {string} [view_mode]
 * @property {[number, string]|false} [search_view_id]
 * @property {string|import("@odoo/owl").Markup} [help]
 * @property {ActionTag} [tag]
 * @property {string} [report_type]
 * @property {Record<string, any>} [params]
 * @property {number[]} [embedded_action_ids]
 * @property {boolean} [cache]
 * @property {string} [jsId]
 * @property {string} [_originalAction]
 * @property {boolean} [_noBreadcrumbs]
 * @property {Record<string, any>} [globalState]
 * @property {Record<ViewType, Controller>} [controllers]
 * @property {CallableFunction} [onClose]
 */
/**
 * @typedef {Omit<Action, "views"> & { type: "ir.actions.act_window", views: any[][],
 * mobile_view_mode?: string }} ActWindowAction
 */
/**
 * @typedef {Action & { type: "ir.actions.act_url", url?: string, close?: boolean }} ActURLAction
 */
/** @typedef {Action & { type: "ir.actions.client" }} ClientAction */
/** @typedef {Action & { type: "ir.actions.server" }} ServerAction */
/**
 * @typedef {Action & { type: "ir.actions.report", report_name?: string, report_file?: string,
 * data?: Record<string, any>, close_on_report_download?: boolean }} ReportAction
 */
/**
 * @typedef {Object} Controller
 * @property {string} jsId
 * @property {Action} action
 * @property {ActionProps} props
 * @property {Config} config
 * @property {boolean} [isMounted]
 * @property {boolean} [lazy]
 * @property {boolean} [virtual]
 * @property {string} [displayName]
 * @property {typeof import("@odoo/owl").Component} [Component]
 * @property {BaseView} [view]
 * @property {BaseView[]} [views]
 * @property {Record<string, any>} [state]
 * @property {Record<string, any>} [currentState]
 * @property {Record<string, any>} [exportedState]
 * @property {Record<string, any>} [__info__]
 * @property {() => any} [getGlobalState]
 * @property {() => any} [getLocalState]
 */
/**
 * @typedef {Object} BaseView
 * @property {ViewType} type
 * @property {boolean} [multiRecord]
 * @property {string} [display_name]
 * @property {string} [icon]
 */
/** @typedef {Record<string, any>} ActionProps */
/** @typedef {Record<string, any>} Config */
/** @typedef {Record<string, any>} UpdateStackOptions */
/**
 * @typedef {Object} DoActionButtonParams
 * @property {string} [type]
 * @property {string|number} [name]
 * @property {string} [special]
 * @property {string} [resModel]
 * @property {number|false} [resId]
 * @property {number[]} [resIds]
 * @property {Context} [context]
 * @property {Context} [buttonContext]
 * @property {any[]} [args]
 * @property {string} [effect]
 * @property {string} [block-ui]
 * @property {boolean} [close]
 * @property {ViewType} [viewType]
 * @property {string} [stackPosition]
 * @property {CallableFunction} [onClose]
 */

/**
 * @typedef {Object} ActionOptions
 * @property {Context} [additionalContext]
 * @property {boolean} [clearBreadcrumbs]
 * @property {CallableFunction} [onClose]
 * @property {boolean} [onCloseIsSpeculative]
 * @property {Object} [props]
 * @property {ViewType} [viewType]
 * @property {"replaceCurrentAction" | "replacePreviousAction"} [stackPosition]
 * @property {(stack: Controller[]) => number} [spliceAt]
 * @property {boolean} [newWindow]
 * @property {boolean} [forceLeave]
 * @property {Object[]} [newStack]
 * @property {boolean} [noEmptyTransition]
 * @property {Function} [onActionReady]
 * @property {number} [poppedLeaves]
 * @property {boolean} [isBreadcrumbRestore]
 * @property {number} [_actionDepth]
 */

export { clearUncommittedChanges };

export { ControllerNotFoundError, standardActionServiceProps };

/**
 * @param {Function} [own]
 * @param {Function} [stolen]
 * @returns {Function|undefined}
 */
function chainOnClose(own, stolen) {
    if (!own) {
        return stolen;
    }
    if (!stolen) {
        return own;
    }
    return async (/** @type {any} */ closeParams) => {
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

export class ActionManager {
    /**
     * The five services the manager and its executors call are bound here, once.
     *
     * They used to be reached as `am.env.services.X` at eleven call sites, each
     * carrying the same three-line `eslint-disable no-restricted-syntax` — one
     * architectural fact copied eleven times. The rule is right to fire:
     * `useService` adds the lifecycle protection a raw read skips. It just has
     * no answer for a plain object with no lifecycle, and the answer was always
     * the second argument `start()` already receives and this class threw away.
     *
     * `services` is a defaulted third parameter, not the second: the second is
     * the router, and `makeActionManager(env, router)` is public API that
     * `enterprise/web_studio/.../editor.js` calls. The default keeps every
     * existing caller working, and a bare `env.services` in a default parameter
     * is not what the lint selector matches (it wants `<holder>.env.services`).
     *
     * Suffixed `Service` uniformly because one of them would otherwise collide:
     * `this.dialog` is the open dialog record, not the dialog service.
     *
     * `?? {}` so a partial env fails where it used to: at the call site that
     * needs the service, not at construction. Four test files build an env by
     * hand with `services: {}` or none, and the reads were previously lazy.
     *
     * @param {import("@web/env").OdooEnv} env
     * @param {RouterLike} [router]
     * @param {Record<string, any>} [services]
     */
    constructor(env, router = _router, services = env.services ?? {}) {
        this.env = env;
        this.router = router;
        this.dialogService = services.dialog;
        this.effectService = services.effect;
        this.notificationService = services.notification;
        this.titleService = services.title;
        this.uiService = services.ui;
        this.breadcrumbCache = new BreadcrumbCache();
        this.navigation = new NavigationTracker();
        this._id = 0;
        this.controllerStack = [];
        /**
         * @type {ActionDispatch|null}
         */
        this._pendingDispatch = null;
        this.dialog = null;
        this.nextDialog = null;
        this._dispatchDepth = 0;

        router.hideKeyFromUrl("globalState");

        this.uninstallActionCacheInvalidation = () => {};

        /** @type {Record<string, (action: any, options: ActionOptions) => Promise<any> | void>} */
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

    async _controllersFromState(/** @type {any} */ state) {
        return controllersFromState(state, this);
    }

    /**
     * @param {any} [closeParams]
     * @param {Function} [removeFn]
     * @return {Promise<void>}
     */
    async _removeDialog(closeParams, removeFn) {
        if (removeFn && this.nextDialog && this.nextDialog.remove === removeFn) {
            const { stolenOnClose, supersededOnClose } = this.nextDialog;
            this.nextDialog = null;
            const inherited = chainOnClose(supersededOnClose, stolenOnClose);
            if (this.dialog && !this.dialog.onClose) {
                this.dialog.onClose = inherited;
            } else {
                await inherited?.(closeParams);
            }
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
     * @returns {Controller[]}
     */
    get _effectiveStack() {
        return this._pendingDispatch?.baseStack ?? this.controllerStack;
    }

    /**
     * @returns {Controller|null}
     */
    get currentController() {
        const stack = this._effectiveStack;
        return stack.at(-1) ?? null;
    }

    /**
     * @returns {Promise<any>}
     */
    async getCurrentAction() {
        const currentController = this.currentController;
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
     * @returns {number}
     */
    _nextId() {
        return ++this._id;
    }

    /**
     * @param {{ forceLeave?: boolean }} [options]
     * @returns {Promise<boolean>}
     */
    async _confirmLeave(options = {}) {
        const token = this.navigation.snapshot();
        const canProceed = await clearUncommittedChanges(this.env, options);
        return canProceed && token.isCurrent();
    }

    async _loadAction(/** @type {any} */ actionRequest, context = {}) {
        return loadAction(actionRequest, context);
    }

    _makeController(/** @type {any} */ params) {
        return makeController(params, this);
    }

    _preprocessAction(/** @type {any} */ action, context = {}) {
        return preprocessAction(action, context, this);
    }

    /**
     * @param {string} viewType
     * @throws {ControllerNotFoundError}
     * @returns {any}
     */
    _getView(viewType) {
        const currentController = this.controllerStack.at(-1);
        if (!currentController) {
            throw new ControllerNotFoundError(
                `Cannot resolve view '${viewType}': the controller stack is empty`,
            );
        }
        if (currentController.action.type !== "ir.actions.act_window") {
            return null;
        }
        const view = currentController.views.find(
            (/** @type {any} */ view) => view.type === viewType,
        );
        return view || null;
    }

    _getBreadcrumbs(/** @type {any} */ stack) {
        return buildBreadcrumbs(stack, this);
    }

    _getActionParams(/** @type {any} */ state) {
        return getActionParams(state);
    }

    /**
     * @param {Action} action
     * @param {ActionProps} props
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
     * @param {Controller[]} [stack]
     * @returns {string|undefined}
     */
    _topActionJsId(stack = this.controllerStack) {
        return stack.at(-1)?.action.jsId;
    }

    /**
     * @param {Controller[]} [stack]
     * @returns {string|undefined}
     */
    _previousActionJsId(stack = this.controllerStack) {
        const topJsId = this._topActionJsId(stack);
        for (let i = stack.length - 1; i >= 0; i--) {
            const jsId = stack[i].action.jsId;
            if (jsId !== topJsId) {
                return jsId;
            }
        }
        return undefined;
    }

    /**
     * @param {ActionOptions} options
     * @param {Controller[]} [stack]
     */
    _computeStackIndex(options, stack = this.controllerStack) {
        if (options.clearBreadcrumbs) {
            return 0;
        } else if (options.stackPosition === "replaceCurrentAction") {
            const currentController = stack.at(-1);
            if (currentController) {
                return stack.findIndex(
                    (ct) => ct.action.jsId === currentController.action.jsId,
                );
            }
        } else if (options.stackPosition === "replacePreviousAction") {
            const target =
                this._previousActionJsId(stack) ?? this._topActionJsId(stack);
            if (target) {
                return stack.findIndex((ct) => ct.action.jsId === target);
            }
        } else if (options.spliceAt) {
            return options.spliceAt(stack);
        }
        return stack.length;
    }

    /**
     * @param {Controller} controller
     * @param {Object} [options]
     * @param {boolean} [options.clearBreadcrumbs]
     * @param {(stack: Controller[]) => number} [options.spliceAt]
     * @param {any[]} [options.newStack]
     * @param {boolean} [options.newWindow]
     * @param {Function} [options.onClose]
     * @param {boolean} [options.noEmptyTransition]
     * @param {Function} [options.onActionReady]
     * @param {boolean} [options.isBreadcrumbRestore]
     * @returns {Promise<any>}
     */
    async _updateUI(controller, options = {}) {
        const action = controller.action;
        const baseStack =
            action.target !== "new" && options.newStack
                ? options.newStack
                : this._effectiveStack;
        const index = this._computeStackIndex(options, baseStack);
        const spliceAt = index < 0 ? baseStack.length : index;
        const nextStack = [...baseStack.slice(0, spliceAt), controller];
        if (action.target !== "new" && options.newWindow) {
            return this._openActionInNewWindow(action, makeActionState(nextStack));
        }
        const dispatch = new ActionDispatch(this, {
            controller,
            action,
            nextStack,
            baseStack,
            restoreStackOnError: options.isBreadcrumbRestore
                ? this._effectiveStack
                : undefined,
        });
        this._prepareControllerConfig(controller, action, nextStack);

        if (action.target === "new") {
            return this._dispatchTargetNew(dispatch, options);
        }
        if (baseStack !== this.controllerStack) {
            this._pendingDispatch = dispatch;
        }
        try {
            return await this._dispatchInline(dispatch, options);
        } finally {
            this.settlePendingDispatch(dispatch);
        }
    }

    /**
     * @param {ActionDispatch} dispatch
     */
    settlePendingDispatch(dispatch) {
        if (this._pendingDispatch === dispatch) {
            this._pendingDispatch = null;
        }
    }

    /**
     * @param {Controller} controller
     * @param {any} action
     * @param {Controller[]} nextStack
     */
    _prepareControllerConfig(controller, action, nextStack) {
        controller.config.breadcrumbs = reactive(
            action.target === "new" ? [] : this._getBreadcrumbs(nextStack),
        );
        controller.config.getDisplayName = () => controller.displayName;
        controller.config.setDisplayName = (/** @type {any} */ displayName) => {
            controller.displayName = displayName;
            if (controller === this.currentController) {
                this.titleService.setParts({
                    action: controller.displayName ?? null,
                });
            }
            if (action.target !== "new") {
                const crumb = controller.config.breadcrumbs.find(
                    (/** @type {any} */ bc) => bc.jsId === controller.jsId,
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
     * @param {ActionDispatch} dispatch
     * @param {Object} options
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
            actionDialogProps.title = action.name ?? null;
        }
        const context = /** @type {Context} */ (action.context);
        const size = DIALOG_SIZES[context.dialog_size];
        if (size) {
            actionDialogProps.size = size;
        }
        for (const key of ["header", "footer"]) {
            if (context[key] !== undefined) {
                actionDialogProps[key] = context[key];
            }
        }
        const superseded = this.nextDialog;
        const stolenOnClose = superseded?.stolenOnClose ?? this.dialog?.onClose;
        const supersededOnClose = superseded
            ? chainOnClose(superseded.ownOnClose, superseded.supersededOnClose)
            : undefined;
        delete this.dialog?.onClose;
        const removeDialogFn = (removeDialogRef.current = this.dialogService.add(
            ActionDialog,
            actionDialogProps,
            {
                onClose: (closeParams) =>
                    this._removeDialog(closeParams, removeDialogFn),
            },
        ));
        if (superseded) {
            this.nextDialog = null;
            superseded.remove();
        }
        this.nextDialog = {
            remove: removeDialogFn,
            onClose: chainOnClose(
                chainOnClose(options.onClose, supersededOnClose),
                stolenOnClose,
            ),
            ownOnClose: options.onClose,
            supersededOnClose,
            stolenOnClose,
        };
        return dispatch.settled();
    }

    /**
     * @param {Controller} controller
     * @param {Action} action
     * @returns {Promise<boolean>}
     */
    async _awaitSkeletonMount(controller, action) {
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
        const onNewerUpdate = () => def.reject(new SupersededError());
        this.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, onNewerUpdate, {
            once: true,
        });
        try {
            await def;
            return true;
        } catch (error) {
            if (!(error instanceof SupersededError)) {
                throw error;
            }
            return false;
        } finally {
            this.env.bus.removeEventListener(
                AppEvent.ACTION_MANAGER_UPDATE,
                onNewerUpdate,
            );
        }
    }

    /**
     * @param {any} action
     * @param {Object} options
     */
    _warnDroppedOnClose(action, options) {
        if (odoo.debug && options.onClose && !options.onCloseIsSpeculative) {
            console.warn(
                `[action] "onClose" is ignored for inline dispatches: ` +
                    `action "${action.id || action.tag || action.type}" ` +
                    `does not open a dialog.`,
            );
        }
    }

    /**
     * @param {ActionDispatch} dispatch
     * @param {Object} options
     * @returns {Promise<void>}
     */
    async _dispatchInline(dispatch, options) {
        const { controller, action } = dispatch;
        this._warnDroppedOnClose(action, options);
        const currentController = this.currentController;
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
            const controllerState = /** @type {Record<string, any>} */ (
                currentController.state
            );
            if (
                controllerState.action === this.router.current.action &&
                controllerState.active_id === this.router.current.active_id &&
                controllerState.resId === this.router.current.resId
            ) {
                this.router.pushState({ globalState }, { sync: true });
            }
        }
        if (controller.action.globalState) {
            controller.props.globalState = controller.action.globalState;
        }

        if (options.clearBreadcrumbs && !options.noEmptyTransition) {
            if (!(await this._awaitSkeletonMount(controller, action))) {
                return;
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
        this.dialogService.closeAll({ noReload: true });
        this.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, controller.__info__);
        await dispatch.settled();
    }

    _openURL(/** @type {any} */ url) {
        return openURL(url, this);
    }

    _openActionInNewWindow(/** @type {any} */ action, /** @type {any} */ state) {
        return openActionInNewWindow(action, state, this);
    }

    _executeCloseAction(action = {}, options = {}) {
        return executeCloseAction(this, action, options);
    }

    /**
     * @param {ActionRequest} actionRequest
     * @param {ActionOptions} options
     * @returns {Promise<number | undefined | void>}
     */
    async doAction(actionRequest, options = {}) {
        this._dispatchDepth++;
        try {
            return await this._doAction(actionRequest, options);
        } finally {
            if (--this._dispatchDepth === 0) {
                this.env.bus.trigger(AppEvent.ACTION_MANAGER_SETTLED);
            }
        }
    }

    /**
     * @param {ActionRequest} actionRequest
     * @param {ActionOptions} options
     * @returns {Promise<number | undefined | void>}
     */
    async _doAction(actionRequest, options = {}) {
        actionLog("doAction", actionRequest, options);
        options = { ...options };
        const actionProm = this._loadAction(actionRequest, options.additionalContext);
        let action = await this.navigation.guard(actionProm);
        action = this._preprocessAction(action, options.additionalContext);
        options.clearBreadcrumbs = action.target === "main" || options.clearBreadcrumbs;

        if (Object.hasOwn(this._actionExecutors, action.type)) {
            if (odoo.debug && actionHandlersRegistry.contains(action.type)) {
                console.warn(
                    `[action] "${action.type}" is dispatched by the action service itself; ` +
                        `the "action_handlers" entry registered for it will never run.`,
                );
            }
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
     * @param {DoActionButtonParams} params
     * @param {Object} [options={}]
     * @returns {Promise<void>}
     */
    async doActionButton(params, options) {
        return executeActionButton(this, params, options);
    }

    /**
     * @param {ViewType} viewType
     * @param {Object} [props={}]
     * @param {{ newWindow?: boolean }} [options={}]
     * @throws {ControllerNotFoundError}
     * @throws {ViewNotFoundError}
     * @returns {Promise<any>}
     */
    async switchView(viewType, props = {}, { newWindow } = {}) {
        await this.navigation.guard(Promise.resolve());
        if (this.dialog || this._pendingDispatch) {
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
        const actionJsId = controller.action.jsId;
        const spliceAt = view.multiRecord
            ? (/** @type {Controller[]} */ stack) => {
                  const at = stack.findIndex((ct) => ct.action.jsId === actionJsId);
                  return at > -1 ? at : stack.length - 1;
              }
            : (/** @type {Controller[]} */ stack) => {
                  const at = stack.findIndex(
                      (ct) =>
                          ct.action.jsId === actionJsId &&
                          !ct.virtual &&
                          !ct.view?.multiRecord,
                  );
                  return at > -1 ? at : stack.length;
              };
        return this._updateUI(newController, { newWindow, spliceAt });
    }

    /**
     * @param {string} jsId
     */
    async restore(jsId) {
        await this.navigation.guard(Promise.resolve());
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
                ...omit(options, "poppedLeaves"),
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
        return this._updateUI(controller, {
            spliceAt: (stack) => {
                const at = stack.findIndex((ct) => ct.jsId === controller.jsId);
                return at > -1 ? at : stack.length;
            },
            isBreadcrumbRestore: true,
        });
    }

    destroy() {
        this.uninstallActionCacheInvalidation();
        this.uninstallActionCacheInvalidation = () => {};
    }

    async loadState(/** @type {any} */ state = undefined) {
        return loadState(this, state);
    }

    async loadAction(
        /** @type {any} */ actionRequest,
        /** @type {any} */ context = {},
    ) {
        const action = await this._loadAction(actionRequest, context);
        return this._preprocessAction(action, context);
    }

    pushState(cStack = this.controllerStack, /** @type {any} */ options = {}) {
        if (!cStack.length) {
            return;
        }

        const newState = makeActionState(cStack);
        actionStorage.setCurrentState(newState);

        cStack.at(-1).state = newState;
        this.router.pushState(newState, Object.assign({ replace: true }, options));
    }
}

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {RouterLike} [router]
 * @param {Record<string, any>} [services]
 * @returns {ActionManager}
 */
export function makeActionManager(env, router = _router, services = env.services) {
    return new ActionManager(env, router, services);
}

export const actionService = {
    dependencies: ["dialog", "effect", "notification", "title", "ui"],
    start(/** @type {any} */ env, /** @type {any} */ services) {
        const am = makeActionManager(env, _router, services);
        am.uninstallActionCacheInvalidation = installActionCacheInvalidation(am);
        return am;
    },
};

registry.category("services").add("action", actionService);
