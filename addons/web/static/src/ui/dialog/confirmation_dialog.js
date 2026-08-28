// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useChildRef } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

export const deleteConfirmationMessage = _t(
    `Ready to make your record disappear into thin air? Are you sure?
It will be gone forever!

Think twice before you click that 'Delete' button!`,
);

export class ConfirmationDialog extends Component {
    static template = "web.ConfirmationDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        title: {
            validate: (/** @type {unknown} */ m) =>
                typeof m === "string" ||
                (typeof m === "object" && typeof m.toString === "function"),
            optional: true,
        },
        body: { type: String, optional: true },
        confirm: { type: Function, optional: true },
        confirmLabel: { type: String, optional: true },
        confirmClass: { type: String, optional: true },
        cancel: { type: Function, optional: true },
        cancelLabel: { type: String, optional: true },
        dismiss: { type: Function, optional: true },
    };
    static defaultProps = {
        confirmLabel: _t("Ok"),
        cancelLabel: _t("Cancel"),
        confirmClass: "btn-primary",
        title: _t("Confirmation"),
    };

    setup() {
        this.env.dialogData.dismiss = () => this.dismiss();
        /** @type {any} */
        this.modalRef = useChildRef();
        this.state = useState({ isProcess: false });
    }

    async cancel() {
        return this.execButton(this.props.cancel);
    }

    async confirm() {
        return this.execButton(this.props.confirm);
    }

    async dismiss() {
        return this.runButton(this.props.dismiss || this.props.cancel);
    }

    /** @param {boolean} disabled */
    setButtonsDisabled(disabled) {
        this.state.isProcess = disabled;
    }

    /**
     * @param {Function} [callback]
     * @returns {Promise<boolean>}
     */
    async runButton(callback) {
        if (this.state.isProcess) {
            return false;
        }
        this.setButtonsDisabled(true);
        if (callback && (await callback()) === false) {
            this.setButtonsDisabled(false);
            return false;
        }
        return true;
    }

    /**
     * @param {Function} [callback]
     */
    async execButton(callback) {
        let shouldClose;
        try {
            shouldClose = await this.runButton(callback);
        } catch (e) {
            this.props.close();
            throw e;
        }
        if (shouldClose) {
            this.props.close();
        }
    }
}

export class AlertDialog extends ConfirmationDialog {
    static template = "web.AlertDialog";
    static props = {
        ...ConfirmationDialog.props,
        contentClass: { type: String, optional: true },
    };
    static defaultProps = {
        ...ConfirmationDialog.defaultProps,
        title: _t("Alert"),
    };
}
