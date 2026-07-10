// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/controller_component - The OWL component that wraps every controller rendered by the action service, plus its placeholder BlankComponent */

import {
    Component,
    onError,
    onMounted,
    onWillUnmount,
    status,
    useChildSubEnv,
    xml,
} from "@odoo/owl";
import { CallbackRecorder } from "@web/core/action_hook";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useDebugCategory } from "@web/services/debug/debug_context";
import { user } from "@web/services/user";
import { View } from "@web/views/view";

import { getActionMode } from "./action_views.js";

const actionRegistry = registry.category("actions");

/**
 * Placeholder shown by the action manager during error recovery and
 * transition states (skeleton view, cleared stack).
 */
class BlankComponent extends Component {
    static props = ["onMounted", "withControlPanel", "*"];
    static template = "web.BlankComponent";
    static components = { ControlPanel };

    setup() {
        useChildSubEnv({ config: { breadcrumbs: [], noBreadcrumbs: true } });
        onMounted(() => this.props.onMounted());
    }
}

/** OWL template for the ControllerComponent — wraps `this.Component` with computed props. */
const ControllerComponentTemplate = xml`<t t-component="Component" t-props="componentProps"/>`;

/** @import { ActionManager } from "./action_service.js" */

/**
 * Build the ControllerComponent class bound to a given {@link ActionManager}.
 *
 * The factory pattern is required because OWL Component classes can't
 * close over service-internal state at the module level — each
 * ActionManager needs a class whose lifecycle hooks read and write *its*
 * instance state, not some other instance's.  This is the *only* sibling
 * module that *writes* the action manager's state (committing the new
 * stack on mount, swapping ``dialog`` to ``nextDialog`` when
 * ``target === "new"``); every other extracted module only reads.
 *
 * Identity stability: ActionManager calls this exactly once in its
 * constructor; the returned class identity is stable across every
 * subsequent ``ACTION_MANAGER:UPDATE`` so OWL's reconciler patches the
 * existing component instance rather than tearing down and remounting.
 * Calling this factory inside a per-render function would silently break
 * SPA navigation continuity.
 *
 * @param {ActionManager} am
 * @returns the bound ControllerComponent class
 */
export function makeControllerComponent(am) {
    /**
     * OWL component wrapping the actual action/view component.
     * Defined once per action manager (not re-created on each navigation).
     * Per-call data (controller, nextStack, promise callbacks) is received via
     * `this.props._context` and stripped from the props passed down to the child.
     */
    return class ControllerComponent extends Component {
        static template = ControllerComponentTemplate;
        static props = { "*": true };

        setup() {
            const { controller, action, nextStack } = this.props._context;
            this.Component = controller.Component;
            this.titleService = useService("title");
            useDebugCategory("action", { action });
            useChildSubEnv({
                config: controller.config,
                pushStateBeforeReload: () => {
                    if (controller.isMounted) {
                        return;
                    }
                    am.pushState(nextStack, { sync: true });
                },
            });
            if (action.target !== "new") {
                this.__beforeLeave__ = new CallbackRecorder();
                this.__getGlobalState__ = new CallbackRecorder();
                this.__getLocalState__ = new CallbackRecorder();
                useBus(am.env.bus, AppEvent.CLEAR_UNCOMMITTED_CHANGES, (ev) => {
                    const callbacks = ev.detail;
                    const beforeLeaveFns = this.__beforeLeave__.callbacks;
                    callbacks.push(...beforeLeaveFns);
                });
                if (this.Component !== View) {
                    useChildSubEnv({
                        __beforeLeave__: this.__beforeLeave__,
                        __getGlobalState__: this.__getGlobalState__,
                        __getLocalState__: this.__getLocalState__,
                    });
                }
            }
            onMounted(this.onMounted);
            onWillUnmount(this.onWillUnmount);
            onError(this.onError);
        }

        onError(error) {
            const { controller, action, reject, removeDialogRef } = this.props._context;
            if (controller.isMounted) {
                // The error occurred on the controller which is already in
                // the DOM, so simply show the error.
                Promise.reject(error);
                return;
            }
            if (!controller.isMounted && status(this) === "mounted") {
                // The error occurred during an onMounted hook of one of the
                // child components.
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
            // Forward the error to the _updateUI caller then restore the
            // action container to an unbroken state.
            reject(error);
            if (action.target === "new") {
                removeDialogRef.current?.();
                return;
            }
            // Fresh read on each access (not a snapshot) — direct property
            // access on the action manager gives the latest value just as
            // the pre-class getter shim ``ctx.getControllerStack()`` did.
            const index = am.controllerStack.findIndex(
                (ct) => ct.jsId === controller.jsId,
            );
            if (index > 0) {
                // The error occurred while rendering an existing controller,
                // so go back to the previous controller from the current
                // faulty one.  This occurs when clicking on a breadcrumb.
                return am.restore(am.controllerStack[index - 1].jsId);
            }
            if (index === 0) {
                // No previous controller to restore, so do nothing but
                // display the error.
                return;
            }
            const lastController = am.controllerStack.at(-1);
            if (lastController) {
                if (lastController.jsId !== controller.jsId) {
                    // The error occurred while rendering a new controller,
                    // so go back to the last non-faulty controller (the
                    // error will still surface to the caller because the
                    // promise was rejected above).
                    return am.restore(lastController.jsId);
                }
            } else {
                am.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {});
            }
        }

        onMounted() {
            const { controller, action, nextStack, resolve } = this.props._context;
            if (action.target === "new") {
                // Remove the previous committed dialog (if any): this
                // mounted dialog replaces it. The synchronous head of the
                // removal chain (dialog service onRemove → am._removeDialog)
                // nulls ``am.dialog`` before the next line runs, and fires
                // no user callback because ``_dispatchTargetNew`` already
                // transferred the previous dialog's ``onClose`` to
                // ``am.nextDialog``.
                am.dialog?.remove();
                // Commit the new dialog and clear the pending slot so the
                // two never alias — ``_dispatchTargetNew`` only removes a
                // still-pending (never mounted) ``nextDialog``.
                am.dialog = am.nextDialog;
                am.nextDialog = null;
            } else {
                controller.getGlobalState = () => {
                    const exportFns = this.__getGlobalState__.callbacks;
                    if (exportFns.length) {
                        return Object.assign({}, ...exportFns.map((fn) => fn()));
                    }
                };
                controller.getLocalState = () => {
                    const exportFns = this.__getLocalState__.callbacks;
                    if (exportFns.length) {
                        return Object.assign({}, ...exportFns.map((fn) => fn()));
                    }
                };
                // Commit the new stack: the controller is mounted.
                am.controllerStack = nextStack;
                am.pushState();
                this.titleService.setParts({ action: controller.displayName });
                browser.sessionStorage.setItem(
                    "current_action",
                    action._originalAction || "{}",
                );
                browser.sessionStorage.setItem("current_lang", user.lang);
            }
            resolve();
            am.env.bus.trigger(
                AppEvent.ACTION_MANAGER_UI_UPDATED,
                getActionMode(action, actionRegistry),
            );
            controller.isMounted = true;
        }

        onWillUnmount() {
            this.props._context.controller.isMounted = false;
        }

        get componentProps() {
            const { _context, ...componentProps } = this.props;
            const { controller } = _context;
            const updateActionState = componentProps.updateActionState;
            componentProps.updateActionState = (newState) =>
                updateActionState(controller, newState);
            if (this.Component === View) {
                componentProps.__beforeLeave__ = this.__beforeLeave__;
                componentProps.__getGlobalState__ = this.__getGlobalState__;
                componentProps.__getLocalState__ = this.__getLocalState__;
            }
            return componentProps;
        }
    };
}
