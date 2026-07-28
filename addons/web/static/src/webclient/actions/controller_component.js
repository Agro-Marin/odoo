// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/controller_component - The OWL component that wraps every controller rendered by the action service */

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
import { AppEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { useDebugCategory } from "@web/services/debug/debug_context";
import { View } from "@web/views/view";

/** OWL template for the ControllerComponent — wraps `this.Component` with computed props. */
const ControllerComponentTemplate = xml`<t t-component="Component" t-props="componentProps"/>`;

/** @import { ActionManager } from "./action_service.js" */

/**
 * Build the ControllerComponent class bound to a given {@link ActionManager}.
 * Factory pattern because the child sub-env and the ``pushStateBeforeReload``
 * hook need *that* manager.
 *
 * ActionManager calls this once in its constructor; the returned class identity
 * must stay stable across every ``ACTION_MANAGER:UPDATE`` so OWL's reconciler
 * patches the existing instance instead of remounting — calling this per-render
 * would break SPA navigation continuity.
 *
 * It does NOT own action-manager state. Each dispatch arrives as an
 * {@link import("./action_dispatch.js").ActionDispatch} on ``props._context``,
 * and the lifecycle hooks below report which outcome happened — ``commit`` /
 * ``fail`` / ``discard``. The component contributes only what is genuinely
 * component-local and cannot be read from outside: OWL's ``status``, and the
 * ``CallbackRecorder``-backed state exporters.
 *
 * @param {ActionManager} am
 * @returns the bound ControllerComponent class
 */
export function makeControllerComponent(am) {
    /**
     * OWL component wrapping the actual action/view component.
     * Defined once per action manager (not re-created on each navigation).
     * Per-dispatch data is received via `this.props._context` and stripped from
     * the props passed down to the child.
     */
    return class ControllerComponent extends Component {
        static template = ControllerComponentTemplate;
        static props = { "*": true };

        setup() {
            const { controller, action, nextStack } = this.props._context;
            this.Component = controller.Component;
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

        /**
         * Collapse a CallbackRecorder into a single state-export function.
         * Returns ``undefined`` (not ``{}``) when nothing registered, which is
         * what the action manager's "did this controller export state?" checks
         * rely on.
         *
         * @param {CallbackRecorder} recorder
         */
        _makeStateExporter(recorder) {
            if (!recorder) {
                return undefined;
            }
            return () => {
                const exportFns = recorder.callbacks;
                if (exportFns.length) {
                    return Object.assign({}, ...exportFns.map((fn) => fn()));
                }
            };
        }

        onMounted() {
            this.props._context.commit({
                getGlobalState: this._makeStateExporter(this.__getGlobalState__),
                getLocalState: this._makeStateExporter(this.__getLocalState__),
            });
        }

        onError(error) {
            return this.props._context.fail(error, { componentStatus: status(this) });
        }

        onWillDestroy() {
            this.props._context.discard({ componentStatus: status(this) });
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
