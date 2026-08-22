// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { buildActionMenuItems, useControllerServices } from "@web/views/view_utils";

/**
 * @extends Component
 */
export class ViewController extends Component {
    /** @type {any} */
    actionService;
    /** @type {any} */
    dialogService;
    /** @type {any} */
    notification;
    /** @type {any} */
    orm;
    /** @type {any} */
    _uiHooks;
    /** @type {any} */
    archInfo;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;

    setupControllerServices() {
        const { action, dialog, notification, orm, uiHooks } = useControllerServices();
        this.actionService = action;
        this.dialogService = dialog;
        this.notification = notification;
        this.orm = orm;
        this._uiHooks = uiHooks;

        this.archInfo = this.props.archInfo;
        this.rootRef = useRef("root");
    }

    setupModel() {}

    setupArch() {}

    setupInteractions() {}

    /**
     * @returns {{ action: Object[], print: Object[] }}
     */
    get actionMenuItems() {
        return buildActionMenuItems(
            this.getStaticActionMenuItems(),
            this.props.info.actionMenus,
        );
    }

    /**
     * @returns {Record<string, Object>}
     */
    getStaticActionMenuItems() {
        return {};
    }

    /**
     * @returns {Object}
     */
    get archiveDialogProps() {
        return {};
    }

    /**
     * @returns {Object}
     */
    get deleteConfirmationDialogProps() {
        return {};
    }

    /**
     * @param {any} clickParams
     * @returns {Promise<boolean | void>}
     */
    async beforeExecuteActionButton(clickParams) {}

    /**
     * @param {any} clickParams
     */
    async afterExecuteActionButton(clickParams) {}
}
