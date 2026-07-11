// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/controller_component - The OWL component that wraps every controller rendered by the action service, plus its placeholder BlankComponent */

import {
    Component,
    onError,
    onMounted,
    onWillDestroy,
    onWillUnmount,
    status,
    useChildSubEnv,
    xml,
} from "@odoo/owl";
import { CallbackRecorder } from "@web/core/action_hook";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
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
 * Factory pattern because each ActionManager needs lifecycle hooks that
 * read/write *its* instance state — this is the only sibling module that
 * writes action-manager state (committing the new stack on mount, swapping
 * ``dialog`` to ``nextDialog`` for ``target === "new"``).
 *
 * ActionManager calls this once in its constructor; the returned class
 * identity must stay stable across every ``ACTION_MANAGER:UPDATE`` so OWL's
 * reconciler patches the existing instance instead of remounting — calling
 * this per-render would break SPA navigation continuity.
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
            onWillDestroy(this.onWillDestroy);
            onError(this.onError);
        }

        onWillDestroy() {
            const { controller, reject } = this.props._context;
            // A controller replaced by a newer ACTION_MANAGER:UPDATE before it
            // ever mounts is destroyed without running onMounted (which
            // resolves) or onError (which rejects). onWillDestroy DOES fire for
            // a destroyed-before-mount component, so settle the outer
            // currentActionProm here — otherwise every doAction awaiter of the
            // superseded action would hang forever. The error service swallows
            // the SupersededError, so this surfaces no dialog.
            if (!controller.isMounted && status(this) !== "mounted") {
                reject(new SupersededError());
            }
        }

        onError(error) {
            const { controller, action, reject, removeDialogRef } = this.props._context;
            if (controller.isMounted) {
                // Controller is already in the DOM — just surface the error.
                Promise.reject(error);
                return;
            }
            if (!controller.isMounted && status(this) === "mounted") {
                // Error happened during a child component's onMounted hook.
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
                if (am.nextDialog?.remove === removeDialogRef.current) {
                    // The failed dialog was still pending: the committed
                    // dialog (if any) survives (_removeDialog's identity
                    // guard), so hand back the onClose stolen at dispatch and
                    // clear the pending slot.
                    if (am.dialog && !am.dialog.onClose) {
                        am.dialog.onClose = am.nextDialog.stolenOnClose;
                    }
                    am.nextDialog = null;
                }
                return;
            }
            const index = am.controllerStack.findIndex(
                (ct) => ct.jsId === controller.jsId,
            );
            if (index > 0) {
                // Error on an existing controller (e.g. breadcrumb click) —
                // go back to the previous one.
                return am.restore(am.controllerStack[index - 1].jsId);
            }
            if (index === 0) {
                // No previous controller to restore; just display the error.
                return;
            }
            const lastController = am.controllerStack.at(-1);
            if (lastController) {
                if (lastController.jsId !== controller.jsId) {
                    // Error while rendering a new controller — go back to the
                    // last non-faulty one (the promise reject above still
                    // surfaces the error to the caller).
                    return am.restore(lastController.jsId);
                }
            } else {
                am.env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {});
            }
        }

        onMounted() {
            const { controller, action, nextStack, resolve } = this.props._context;
            if (action.target === "new") {
                // Remove the previously committed dialog (if any) — this
                // mounted dialog replaces it. The removal chain synchronously
                // nulls am.dialog and fires no user callback, since
                // _dispatchTargetNew already moved onClose to am.nextDialog.
                am.dialog?.remove();
                // Commit the new dialog and clear the pending slot so the two
                // never alias (_dispatchTargetNew only removes a still-pending,
                // never-mounted nextDialog).
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
            // Flip isMounted before resolve()/trigger: code resumed by the
            // resolved doAction promise (or the UI_UPDATED listeners) must
            // never observe `false` on an actually-mounted controller.
            controller.isMounted = true;
            resolve();
            am.env.bus.trigger(
                AppEvent.ACTION_MANAGER_UI_UPDATED,
                getActionMode(action, actionRegistry),
            );
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
