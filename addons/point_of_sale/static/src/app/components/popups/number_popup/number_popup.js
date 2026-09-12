/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { buttonsType, Numpad } from "@point_of_sale/app/components/numpad/numpad";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.number");
export class NumberPopup extends Component {
    static template = "point_of_sale.NumberPopup";
    static components = { Numpad, Dialog };
    static props = {
        title: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        buttons: { type: buttonsType, optional: true },
        startingValue: { type: [Number, String], optional: true },
        feedback: { type: Function, optional: true },
        formatDisplayedValue: { type: Function, optional: true },
        placeholder: { type: String, optional: true },
        isValid: { type: Function, optional: true },
        confirmButtonLabel: { type: String, optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        title: _t("Amount of guests"),
        startingValue: "",
        isValid: () => true,
        formatDisplayedValue: (x) => x,
        feedback: () => false,
    };

    setup() {
        useLifecycleLog(log);
        this.numberBuffer = useService("number_buffer");
        this.numberBuffer.use({
            triggerAtInput: ({ buffer }) => (this.state.buffer = buffer),
            captureWithOverlay: true,
        });
        useHotkey("enter", () => this.confirm());
        useHotkey("escape", () => this.cancel());
        this.state = useState({
            buffer: this.props.startingValue,
        });
    }

    get confirmButtonLabel() {
        return this.props.confirmButtonLabel || _t("Confirm");
    }

    confirm() {
        this.numberBuffer.capture();
        const valid = this.props.isValid(this.state.buffer);
        log.logic("confirm", () => ({
            title: this.props.title,
            buffer: this.state.buffer,
            valid,
        }));
        if (!valid) {
            return;
        }
        this.props.getPayload(this.state.buffer);
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
