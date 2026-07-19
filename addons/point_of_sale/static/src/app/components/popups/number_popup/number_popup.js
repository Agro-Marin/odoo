/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { buttonsType, Numpad } from "@point_of_sale/app/components/numpad/numpad";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";
import { Dialog } from "@web/ui/dialog/dialog";
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
        this.numberBuffer = useService("number_buffer");
        this.numberBuffer.use({
            triggerAtInput: ({ buffer }) => (this.state.buffer = buffer),
            // This popup is itself an overlay: it must keep receiving global
            // keyboard input while it is open.
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
        // Flush any key/click still sitting in the number buffer's debounce
        // window before reading the value. `_bufferEvents` defers handling to a
        // `setTimeout`, so a confirm that lands in the same task as the last
        // input (fast click, Enter right after a digit, tours) used to submit
        // the *previous* buffer — typing "0" then confirming yielded "".
        this.numberBuffer.capture();
        // The confirm button is disabled when invalid, but the Enter hotkey also
        // routes here — gate it so both share one validity check and an invalid
        // buffer can't be submitted via the keyboard.
        if (!this.props.isValid(this.state.buffer)) {
            return;
        }
        this.props.getPayload(this.state.buffer);
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
