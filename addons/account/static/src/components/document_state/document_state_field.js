/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";
import { usePopover } from "@web/ui/popover";

export class DocumentStatePopover extends Component {
    static template = "account.DocumentStatePopover";
    static props = {
        close: Function,
        copyText: Function,
        message: String,
    };
}

export class DocumentState extends SelectionField {
    static template = "account.DocumentState";

    setup() {
        super.setup();
        // `usePopover` owns the open/closed state and closes on unmount. Tracking
        // it by hand missed the click-away close, which left the widget believing
        // the popover was still open and refusing to reopen it.
        this.popover = usePopover(DocumentStatePopover, {
            closeOnClickAway: true,
            position: "top",
        });
        this.notification = useService("notification");
    }

    get message() {
        return this.props.record.data.message;
    }

    async copyText() {
        try {
            await navigator.clipboard.writeText(this.message);
            this.notification.add(_t("Text copied"), { type: "success" });
        } catch {
            this.notification.add(_t("Could not copy to clipboard"), {
                type: "warning",
            });
        }
        this.popover.close();
    }

    showMessagePopover(ev) {
        if (this.popover.isOpen) {
            this.popover.close();
            return;
        }
        this.popover.open(ev.currentTarget, {
            message: this.message,
            copyText: this.copyText.bind(this),
        });
    }
}

registry.category("fields").add("account_document_state", {
    ...selectionField,
    component: DocumentState,
});
