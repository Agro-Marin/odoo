// @ts-check
/** @odoo-module native */

import { reportUncaught } from "@web/core/errors/error_utils";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { SupersededError } from "@web/core/utils/concurrency";

import { actionStorage } from "./action_storage.js";
import { getActionMode } from "./action_views.js";
import { BlankComponent } from "./blank_component.js";

const actionRegistry = registry.category("actions");

/** @import { Action, ActionManager, Controller } from "./action_service.js" */

export class ActionDispatch {
    /**
     * @param {ActionManager} am
     * @param {Object} params
     * @param {Controller} params.controller
     * @param {Action} params.action
     * @param {Controller[]} params.nextStack
     * @param {Controller[]} [params.baseStack]
     * @param {Controller[]} [params.restoreStackOnError]
     */
    constructor(am, { controller, action, nextStack, baseStack, restoreStackOnError }) {
        this.am = am;
        this.controller = controller;
        this.action = action;
        this.nextStack = nextStack;
        this.baseStack = baseStack ?? am.controllerStack;
        this.restoreStackOnError = restoreStackOnError;
        /**
         * @type {import("./navigation_token.js").NavigationToken}
         */
        this.token = am.navigation.snapshot();
        /**
         * @type {{ current?: Function }}
         */
        this.removeDialogRef = { current: undefined };
        /**
         * @type {Promise<void>}
         */
        this.promise = new Promise((resolve, reject) => {
            this._resolve = resolve;
            this._reject = reject;
        });
    }

    /**
     * @param {Object} exporters
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
            am.settlePendingDispatch(this);
            am.pushState();

            am.titleService.setParts({ action: controller.displayName });
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

    _commitDialog() {
        const { am } = this;
        am.dialog?.remove();
        am.dialog = am.nextDialog;
        am.nextDialog = null;
    }

    /**
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
     * @param {{ componentStatus: string }} ctx
     */
    discard({ componentStatus }) {
        if (!this.controller.isMounted && componentStatus !== "mounted") {
            this._reject(new SupersededError());
        }
    }

    /**
     * @param {Error} error
     * @param {{ componentStatus: string }} ctx
     * @returns {any}
     */
    fail(error, { componentStatus }) {
        const { am, controller, action } = this;
        if (controller.isMounted) {
            reportUncaught(error);
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
            reportUncaught(error);
            return;
        }
        this._reject(error);
        if (action.target === "new") {
            return this._releasePendingDialog();
        }
        return this._restoreStack();
    }

    _releasePendingDialog() {
        this.removeDialogRef.current?.();
    }

    /**
     * @returns {any}
     */
    _restoreStack() {
        const { am, controller, baseStack } = this;
        if (am.controllerStack !== baseStack) {
            am.controllerStack = baseStack;
        }
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
