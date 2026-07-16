/** @odoo-module native */
import { Component, onMounted, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
export class AutoresizeInput extends Component {
    static template = "mail.AutoresizeInput";
    static props = {
        autofocus: { type: Boolean, optional: true },
        className: { type: String, optional: true },
        enabled: { optional: true },
        onCancel: { type: Function, optional: true },
        onValidate: { type: Function, optional: true },
        placeholder: { type: String, optional: true },
        value: { type: String, optional: true },
    };
    static defaultProps = {
        autofocus: false,
        className: "",
        enabled: true,
        onCancel: () => {},
        onValidate: () => {},
        placeholder: "",
    };

    setup() {
        super.setup();
        this.state = useState({
            value: this.props.value,
            isFocused: false,
        });
        this.inputRef = useRef("input");
        onWillUpdateProps((nextProps) => {
            // don't clobber a focused input: a bus-driven rename arriving
            // while the user is editing would destroy their keystrokes
            if (this.props.value !== nextProps.value && !this.state.isFocused) {
                this.state.value = nextProps.value;
            }
        });
        useAutoresize(this.inputRef);
        onMounted(() => {
            if (this.props.autofocus) {
                this.inputRef.el.focus();
                this.inputRef.el.setSelectionRange(-1, -1);
            }
        });
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onKeydownInput(ev) {
        switch (ev.key) {
            case "Enter":
                this.inputRef.el.blur();
                break;
            case "Escape":
                ev.stopPropagation();
                this.state.value = this.props.value;
                this.cancelled = true;
                this.inputRef.el.blur();
                break;
        }
    }

    onBlurInput() {
        this.state.isFocused = false;
        if (this.cancelled) {
            // Escape restores the original value: don't validate (a rename
            // RPC on every cancelled edit otherwise). Still notify the owner:
            // it may need to leave its editing mode (e.g. chat window thread
            // rename), which `onValidate` used to do as a side effect.
            this.cancelled = false;
            this.props.onCancel();
            return;
        }
        this.props.onValidate(this.state.value);
    }
}
