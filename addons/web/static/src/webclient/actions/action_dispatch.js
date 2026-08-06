// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_dispatch */

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
         * The navigation this dispatch belongs to: the token minted by the
         * entry point (doAction / switchView / restore / loadState) that led
         * here, read off the manager's tracker at dispatch creation. Stages
         * that must ask "has a newer navigation started?" ask this token and
         * fail with the one documented outcome, `SupersededError`.
         *
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
            // The dispatch is over the moment its stack is published. Kept
            // pending, `_effectiveStack` would keep answering with the base
            // stack while the `UI-UPDATED` listeners below run, so anyone
            // reading `currentController` inside that event would see the
            // controller this dispatch just replaced — web_studio's
            // `inStudio` flag never saw the studio action land and every
            // later `leave()` threw "leave when not in studio???".
            // (`_updateUI`'s `finally` re-settles; the `===` guard inside
            // makes both no-ops after the first.)
            am.settlePendingDispatch(this);
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
