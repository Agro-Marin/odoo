// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/controller_component */

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
import { useDebugCategory } from "@web/core/debug/debug_context";
import { AppEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { View } from "@web/views/view";

const ControllerComponentTemplate = xml`<t t-component="Component" t-props="componentProps"/>`;

/** @import { ActionManager } from "./action_service.js" */

/**
 * @param {ActionManager} am
 */
export function makeControllerComponent(am) {
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

        /** @param {any} error */
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
            componentProps.updateActionState = (/** @type {any} */ newState) =>
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
