/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useDateTimePicker } from "@web/components/datetime";
import { ConversionError, formatDate, formatDateTime, parseDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";
import { pick } from "@web/core/utils/collections/objects";
import { effect } from "@web/core/utils/reactive";

import {
    basicContainerBuilderComponentProps,
    useBuilderComponent,
    useInputBuilderComponent,
} from "../utils.js";
import { BuilderComponent } from "./builder_component.js";
import { BuilderTextInputBase, textInputBasePassthroughProps } from "./builder_text_input_base.js";

const { DateTime } = luxon;

export class BuilderDateTimePicker extends Component {
    static template = "html_builder.BuilderDateTimePicker";
    static props = {
        ...basicContainerBuilderComponentProps,
        ...textInputBasePassthroughProps,
        type: { type: [{ value: "date" }, { value: "datetime" }], optional: true },
        format: { type: String, optional: true },
        acceptEmptyDate: { type: Boolean, optional: true },
    };
    static defaultProps = {
        type: "datetime",
        acceptEmptyDate: true,
    };
    static components = {
        BuilderComponent,
        BuilderTextInputBase,
    };

    setup() {
        useBuilderComponent();
        this.defaultValue = DateTime.now().toUnixInteger().toString();
        const { state, commit, preview } = useInputBuilderComponent({
            id: this.props.id,
            defaultValue: this.props.acceptEmptyDate ? undefined : this.defaultValue,
            formatRawValue: this.formatRawValue.bind(this),
            parseDisplayValue: this.parseDisplayValue.bind(this),
        });
        this.domState = state;
        this.state = useState({});
        effect(
            ({ value }) => {
                // State to display in the input.
                this.state.value = value;
            },
            [state]
        );

        this.commit = (userInputValue) => {
            this.isPreviewing = false;
            const result = commit(userInputValue);
            return result;
        };

        this.preview = (userInputValue) => {
            this.isPreviewing = true;
            preview(userInputValue);
        };

        const minDate = DateTime.fromObject({ year: 1000 });
        const maxDate = DateTime.now().plus({ year: 200 });
        const getPickerProps = () => ({
            type: this.props.type,
            minDate,
            maxDate,
            value: this.getCurrentValueDateTime(),
            rounding: 1,
        });

        // A countdown or a form field is set to the minute; seconds are noise
        // the user should neither see nor be able to edit. `rounding: 1` keeps
        // them out of the picker, and this format keeps them out of the input.
        const isDateOnly = this.props.type === "date";
        this.formatDateTime = isDateOnly ? formatDate : formatDateTime;
        this.displayFormat = isDateOnly
            ? localization.dateFormat
            : localization.dateTimeFormat.replace(":ss", "").replace(".ss", "");

        this.dateTimePicker = useDateTimePicker({
            target: "root",
            format: this.props.format,
            get pickerProps() {
                return getPickerProps();
            },
            onApply: (value) => {
                this.commit(this.formatDateTime(value));
            },
            onChange: (value) => {
                const dateString = this.formatDateTime(value);
                this.preview(dateString);
                this.state.value = this.parseDisplayValue(dateString);
            },
        });
    }

    /**
     * @returns {DateTime} the current value of the datetime picker
     */
    getCurrentValueDateTime() {
        return this.domState.value ? DateTime.fromSeconds(parseInt(this.domState.value)) : false;
    }

    /**
     * @param {String} rawValue - the raw value in seconds
     * @returns {String} a formatted date string
     */
    formatRawValue(rawValue) {
        return rawValue
            ? this.formatDateTime(DateTime.fromSeconds(parseInt(rawValue)), {
                  format: this.displayFormat,
              })
            : "";
    }

    /**
     * @param {String} displayValue - representing a date
     * @returns {String} number of seconds
     */
    parseDisplayValue(displayValue) {
        if (displayValue === "" && this.props.acceptEmptyDate) {
            return undefined;
        }
        try {
            const parsedDateTime = parseDateTime(displayValue);
            if (parsedDateTime) {
                return parsedDateTime.set({ second: 0, millisecond: 0 }).toUnixInteger().toString();
            }
        } catch (e) {
            // A ConversionError means displayValue is an invalid date: keep
            // the current value, unless previewing or empty, in which case
            // fall back to the default value.
            if (!(e instanceof ConversionError)) {
                throw e;
            }
            if (!this.isPreviewing && displayValue !== "") {
                return this.domState.value;
            }
        }
        return this.defaultValue;
    }

    /**
     * @returns {String} a formatted date string
     */
    get displayValue() {
        return this.state.value !== undefined ? this.formatRawValue(this.state.value) : undefined;
    }

    get textInputBaseProps() {
        return pick(this.props, ...Object.keys(textInputBasePassthroughProps));
    }

    onFocus() {
        this.dateTimePicker.open();
    }
}
