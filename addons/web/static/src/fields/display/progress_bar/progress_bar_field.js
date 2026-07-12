// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/progress_bar/progress_bar_field - Editable progress bar displaying current/max numeric values */

import { Component, useRef, useState } from "@odoo/owl";
import { getFieldCodec } from "@web/core/field_codec";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { useInputField } from "@web/fields/input_field_hook";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";
import { parseFloat, parseInteger } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 *  maxValueField?: string | number;
 *  currentValueField?: string;
 *  isEditable?: boolean;
 *  isCurrentValueEditable?: boolean;
 *  isMaxValueEditable?: boolean;
 *  title?: string;
 *  overflowClass?: string;
 * }} ProgressBarFieldProps
 */

/** @extends {Component<ProgressBarFieldProps>} */
export class ProgressBarField extends Component {
    static template = "web.ProgressBarField";
    static props = {
        ...standardFieldProps,
        maxValueField: { type: [String, Number], optional: true },
        currentValueField: { type: String, optional: true },
        isEditable: { type: Boolean, optional: true },
        isCurrentValueEditable: { type: Boolean, optional: true },
        isMaxValueEditable: { type: Boolean, optional: true },
        title: { type: String, optional: true },
        overflowClass: { type: String, optional: true },
    };

    setup() {
        useNumpadDecimal();
        this.root = useRef("numpadDecimal");

        const {
            currentValueField,
            maxValueField: maxValueFieldProp,
            name,
        } = this.props;
        this.currentValueField = currentValueField ? currentValueField : name;
        if (maxValueFieldProp) {
            this.maxValueField = maxValueFieldProp;
        }
        this.currentValueRef = useInputField({
            getValue: () => this.formatValue(this.currentValueField, this.currentValue),
            parse: (v) => this.parseValue(this.currentValueField, v),
            refName: "currentValue",
            fieldName: this.currentValueField,
            shouldSave: () => this.props.readonly,
        });
        // Only a string maxValueField names a real record field; in percentage
        // mode (numeric literal) or when absent, the max-value input is never
        // rendered (template t-else), so the hook stays inert (ref.el null).
        // Guarding to `undefined` here avoids silently binding this input to the
        // MAIN field name via useInputField's `fieldName || props.name` fallback.
        const maxValueField =
            typeof this.maxValueField === "string" ? this.maxValueField : undefined;
        this.maxValueRef = useInputField({
            getValue: () => this.formatValue(maxValueField, this.maxValue),
            parse: (v) => this.parseValue(maxValueField, v),
            refName: "maxValue",
            fieldName: maxValueField,
            shouldSave: () => this.props.readonly,
        });

        this.state = useState({
            isEditing: false,
        });
    }

    /** @returns {boolean} Whether the progress bar is editable in the current context. */
    get isEditable() {
        return this.props.isEditable && !this.props.readonly;
    }
    /** @returns {boolean} Whether maxValueField is a fixed number (percentage mode) rather than a field name. */
    get isPercentage() {
        return (
            !this.props.maxValueField ||
            !isNaN(/** @type {number} */ (this.props.maxValueField))
        );
    }

    /** @returns {number} Current progress value from the record, defaulting to 0. */
    get currentValue() {
        return this.props.record.data[this.currentValueField] || 0;
    }

    /** @returns {number} Maximum value: literal number, record field, or 100 as default. */
    get maxValue() {
        if (typeof this.maxValueField === "number") {
            return this.maxValueField;
        }
        return this.props.record.data[this.maxValueField] || 100;
    }

    /** @returns {string} CSS class for the bar color; overflow class when value exceeds max. */
    get progressBarColorClass() {
        return this.currentValue > this.maxValue
            ? this.props.overflowClass
            : "bg-primary";
    }

    /**
     * @param {string} fieldName - Record field to determine the formatter type
     * @param {number} value - Numeric value to format
     * @param {boolean} [humanReadable] - Use human-readable format (defaults to true when not editing)
     * @returns {string} Formatted string representation
     */
    formatValue(fieldName, value, humanReadable = !this.state.isEditing) {
        const type = this.props.record.fields[fieldName]?.type ?? "integer";
        // NOTE: `field`/`digits` are intentionally NOT forwarded here — doing so
        // is pinned against by the max-value formatting tests (they expect the
        // default 2-decimal float rendering). Honoring the column's digits
        // precision is deferred until those expectations are revisited.
        return getFieldCodec(type).format(value, { humanReadable });
    }

    /**
     * @param {boolean} [humanReadable] - Use human-readable format
     * @returns {string} Formatted current value
     */
    formatCurrentValue(humanReadable = !this.state.isEditing) {
        return this.formatValue(
            this.currentValueField,
            this.currentValue,
            humanReadable,
        );
    }

    /**
     * @param {boolean} [humanReadable] - Use human-readable format
     * @returns {string} Formatted max value
     */
    formatMaxValue(humanReadable = !this.state.isEditing) {
        return this.formatValue(
            /** @type {string} */ (this.maxValueField),
            this.maxValue,
            humanReadable,
        );
    }

    /**
     * @param {string} fieldName - Record field to determine the parser type
     * @param {string} value - Raw input string to parse
     * @returns {number} Parsed numeric value
     */
    parseValue(fieldName, value) {
        return this.props.record.fields[fieldName]?.type === "integer"
            ? parseInteger(value, { allowOperation: true })
            : parseFloat(value, { allowOperation: true });
    }

    /** Exits editing mode when focus leaves both input fields. */
    onInputBlur() {
        if (
            document.activeElement !== this.maxValueRef.el &&
            document.activeElement !== this.currentValueRef.el
        ) {
            this.state.isEditing = false;
        }
    }
    /** Enters editing mode when an input field gains focus. */
    onInputFocus() {
        this.state.isEditing = true;
    }
}

export const progressBarField = {
    component: ProgressBarField,
    displayName: _t("Progress Bar"),
    supportedOptions: [
        {
            label: _t("Can edit value"),
            name: "editable",
            type: "boolean",
        },
        {
            label: _t("Can edit max value"),
            name: "edit_max_value",
            type: "boolean",
        },
        {
            label: _t("Current value field"),
            name: "current_value",
            type: "field",
            availableTypes: ["integer", "float"],
            help: _t(
                "Use to override the display value (e.g. if your progress bar is a computed percentage but you want to display the actual field value instead).",
            ),
        },
        {
            label: _t("Max value field"),
            name: "max_value",
            type: "field",
            availableTypes: ["integer", "float"],
            help: _t(
                "Field that holds the maximum value of the progress bar. If set, will be displayed next to the progress bar (e.g. 10 / 200).",
            ),
        },
        {
            label: _t("Overflow style"),
            name: "overflow_class",
            type: "string",
            availableTypes: ["integer", "float"],
            help: _t(
                "Bootstrap classname to customize the style of the progress bar when the maximum value is exceeded",
            ),
            default: "bg-secondary",
        },
    ],
    supportedTypes: ["integer", "float"],
    extractProps: ({ attrs, options }) => ({
        maxValueField: options.max_value,
        currentValueField: options.current_value,
        isEditable: !options.readonly && options.editable,
        isCurrentValueEditable: options.editable && !options.edit_max_value,
        isMaxValueEditable: options.editable && options.edit_max_value,
        title: attrs.title,
        overflowClass: options.overflow_class || "bg-secondary",
    }),
};

registerField("progressbar", progressBarField);
