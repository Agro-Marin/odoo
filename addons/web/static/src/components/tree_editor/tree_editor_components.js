// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list/tags_list";
import { IN_RANGE_OPTIONS } from "@web/core/tree/in_range_options";
import {
    matchInRangeProviderOption,
    resolveInRangeProviderOption,
} from "@web/core/tree/in_range_providers";
export class Input extends Component {
    static props = {
        value: true,
        update: Function,
        placeholder: { type: String, optional: true },
        startEmpty: { type: Boolean, optional: true },
    };
    static template = "web.TreeEditor.Input";

    /** @type {import("@odoo/owl").Ref<HTMLInputElement>} */
    inputRef;

    setup() {
        this.inputRef = useRef("input");
    }

    /**
     * @param {Event} ev
     */
    async onChange(ev) {
        const el = /** @type {HTMLInputElement} */ (ev.target);
        await this.props.update(el.value);
        const input = /** @type {HTMLInputElement | null} */ (this.inputRef.el);
        if (!this.props.startEmpty && input) {
            input.value = this.props.value;
        }
    }
}

export class Select extends Component {
    static props = {
        value: true,
        update: Function,
        options: { type: Array },
        placeholder: { type: String, optional: true },
        addBlankOption: { type: Boolean, optional: true },
        optionGroups: { type: Object, optional: true },
    };
    static template = "web.TreeEditor.Select";

    /**
     * @returns {{ungrouped: any[], groups: Array<[string, any[]]>}}
     */
    get renderedOptions() {
        const groups = new Map();
        const ungrouped = [];
        for (const option of this.props.options) {
            const group = this.props.optionGroups?.[this.serialize(option[0])];
            if (!group) {
                ungrouped.push(option);
                continue;
            }
            if (!groups.has(group)) {
                groups.set(group, []);
            }
            groups.get(group).push(option);
        }
        return { ungrouped, groups: [...groups] };
    }

    /**
     * @param {string} value
     * @returns {any}
     */
    deserialize(value) {
        return JSON.parse(value);
    }

    /**
     * @param {any} value
     * @returns {string}
     */
    serialize(value) {
        return JSON.stringify(value);
    }
}

export class Range extends Component {
    static props = {
        value: { type: Array },
        update: Function,
        editorInfo: Object,
    };
    static template = "web.TreeEditor.Range";

    /**
     * @param {0|1} index
     * @param {any} newValue
     */
    update(index, newValue) {
        const result = [...this.props.value];
        result[index] = newValue;
        return this.props.update(result);
    }
}

export class InRange extends Component {
    static props = {
        value: { type: Array },
        update: Function,
        valueTypeEditorInfo: Object,
        betweenEditorInfo: Object,
    };
    static template = "web.TreeEditor.InRange";
    static options = IN_RANGE_OPTIONS;

    /**
     * @returns {string}
     */
    get selectedValueType() {
        const [fieldType, valueType, start, end] = this.props.value;
        if (valueType !== "custom range") {
            return valueType;
        }
        return matchInRangeProviderOption(fieldType, start, end) || valueType;
    }

    /**
     * @param {string} newValueType
     */
    updateValueType(newValueType) {
        const [fieldType] = this.props.value;
        if (newValueType === this.selectedValueType) {
            return;
        }
        const bounds = resolveInRangeProviderOption(newValueType, fieldType);
        if (bounds) {
            return this.props.update([fieldType, "custom range", ...bounds]);
        }
        const values =
            newValueType === "custom range"
                ? this.props.betweenEditorInfo.defaultValue()
                : [false, false];
        return this.props.update([fieldType, newValueType, ...values]);
    }
    /**
     * @param {[any, any]} values
     */
    updateValues(values) {
        const [fieldType, currentValueType] = this.props.value;
        return this.props.update([fieldType, currentValueType, ...values]);
    }
}

export class List extends Component {
    static components = { TagsList };
    static props = {
        value: { type: Array },
        update: Function,
        editorInfo: Object,
    };
    static template = "web.TreeEditor.List";

    /** @returns {Array<{text: string, colorIndex: number, onDelete: Function}>} */
    get tags() {
        const { isSupported, stringify } = this.props.editorInfo;
        return this.props.value.map(
            (/** @type {any} */ val, /** @type {number} */ index) => ({
                text: stringify(val),
                colorIndex: isSupported(val) ? 0 : 2,
                onDelete: () => {
                    this.props.update([
                        ...this.props.value.slice(0, index),
                        ...this.props.value.slice(index + 1),
                    ]);
                },
            }),
        );
    }

    /**
     * @param {any} newValue
     */
    update(newValue) {
        return this.props.update([...this.props.value, newValue]);
    }
}
