// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { omit } from "@web/core/utils/collections/objects";

import { DateTimePicker } from "./datetime_picker.js";
import { useDateTimePicker } from "./datetime_picker_hook.js";
/** @typedef {import("@web/core/l10n/luxon").DateTime} DateTime */

/**
 * @typedef {import("./datetime_picker").DateTimePickerProps & {
 * class?: string;
 * disabled?: boolean;
 * format?: string;
 * id?: string;
 * onApply?: (value: DateTime) => any;
 * onChange?: (value: DateTime) => any;
 * placeholder?: string;
 * }} DateTimeInputProps
 */

const dateTimeInputOwnProps = {
    format: { type: String, optional: true },
    id: { type: String, optional: true },
    class: { type: String, optional: true },
    onChange: { type: Function, optional: true },
    onApply: { type: Function, optional: true },
    placeholder: { type: String, optional: true },
    disabled: { type: Boolean, optional: true },
};

/** Everything above is consumed here and must not reach the picker. */
const DATE_TIME_INPUT_OWN_PROP_NAMES = Object.keys(dateTimeInputOwnProps);

/** @extends {Component<DateTimeInputProps>} */
export class DateTimeInput extends Component {
    static props = {
        ...DateTimePicker.props,
        ...dateTimeInputOwnProps,
    };

    static template = "web.DateTimeInput";

    setup() {
        const getPickerProps = () =>
            omit(this.props, .../** @type {any} */ (DATE_TIME_INPUT_OWN_PROP_NAMES));

        useDateTimePicker(
            /** @type {any} */ ({
                format: this.props.format,
                showSeconds: /** @type {number} */ (this.props.rounding) <= 0,
                get pickerProps() {
                    return getPickerProps();
                },
                onApply: (/** @type {any} */ value) => this.props.onApply?.(value),
                onChange: (/** @type {any} */ value) => this.props.onChange?.(value),
            }),
        );
    }
}
