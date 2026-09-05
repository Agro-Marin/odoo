// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useConfirmButton } from "@web/ui/dialog/confirm_button_hook";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * A dialog around one editable value that is validated before it is handed
 * back: the subclass names the value it starts from, how to validate it and
 * what to say when validation fails; this class owns the state, the confirm
 * button's disabled window, the notification and the close.
 */
export class EditorDialog extends Component {
    static components = { Dialog };

    /** @type {(disabled: boolean) => void} */
    setConfirmDisabled;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ value: any }} */
    state;

    setup() {
        this.notification = useService("notification");
        this.state = useState({ value: this.initialValue });
        this.setConfirmDisabled = useConfirmButton();
    }

    /** @returns {any} */
    get initialValue() {
        throw new Error("EditorDialog: `initialValue` is the subclass's to define");
    }

    /** @returns {string} */
    get invalidMessage() {
        throw new Error("EditorDialog: `invalidMessage` is the subclass's to define");
    }

    /** @returns {Promise<boolean> | boolean} */
    isValueValid() {
        throw new Error("EditorDialog: `isValueValid` is the subclass's to define");
    }

    /** @param {any} value */
    update(value) {
        this.state.value = value;
    }

    async onConfirm() {
        this.setConfirmDisabled(true);
        let valid;
        try {
            valid = await this.isValueValid();
        } finally {
            this.setConfirmDisabled(false);
        }
        if (!valid) {
            this.notification.add(this.invalidMessage, { type: "danger" });
            return;
        }
        this.props.onConfirm(this.state.value);
        this.props.close();
    }

    onDiscard() {
        this.props.close();
    }
}
