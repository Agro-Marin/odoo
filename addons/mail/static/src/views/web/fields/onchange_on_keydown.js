/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { patch } from "@web/core/utils/patch";
import { useDebounced } from "@web/core/utils/timing";
import { CharField, charField } from "@web/fields/basic/char/char_field";
import { TextField, textField } from "@web/fields/basic/text/text_field";
const onchangeOnKeydownMixin = () => ({
    setup() {
        super.setup(...arguments);

        if (this.props.onchangeOnKeydown) {
            const input = this.input || this.textareaRef;

            const triggerOnChange = useDebounced(
                this.triggerOnChange,
                this.props.keydownDebounceDelay,
            );
            useEffect(
                /** @param {HTMLElement|null} el */
                (el) => {
                    if (el) {
                        el.addEventListener("keydown", triggerOnChange);
                        return () => {
                            el.removeEventListener("keydown", triggerOnChange);
                        };
                    }
                },
                () => [input.el],
            );
        }
    },

    triggerOnChange() {
        const input = this.input || this.textareaRef;
        input.el.dispatchEvent(new Event("change"));
    },
});

patch(CharField.prototype, onchangeOnKeydownMixin());
patch(TextField.prototype, onchangeOnKeydownMixin());

CharField.props = {
    ...CharField.props,
    onchangeOnKeydown: { type: Boolean, optional: true },
    keydownDebounceDelay: { type: Number, optional: true },
};

TextField.props = {
    ...TextField.props,
    onchangeOnKeydown: { type: Boolean, optional: true },
    keydownDebounceDelay: { type: Number, optional: true },
};

/**
 * @param {(fieldInfo: Object) => Object} baseExtractProps
 * @returns {(fieldInfo: Object) => Object}
 */
function extendExtractProps(baseExtractProps) {
    return /** @param {{attrs: Object, options: Object, viewType?: string}} fieldInfo */ (
        fieldInfo,
    ) =>
        Object.assign(baseExtractProps(fieldInfo), {
            onchangeOnKeydown: exprToBoolean(fieldInfo.attrs.onchange_on_keydown),
            keydownDebounceDelay: fieldInfo.attrs.keydown_debounce_delay
                ? Number(fieldInfo.attrs.keydown_debounce_delay)
                : 2000,
        });
}
charField.extractProps = extendExtractProps(charField.extractProps);
textField.extractProps = extendExtractProps(textField.extractProps);
