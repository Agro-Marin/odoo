// @ts-check
/** @odoo-module native */

/** @module @web/components/tree_editor/tree_editor_components */

import { Component } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list/tags_list";
import { IN_RANGE_OPTIONS } from "@web/core/tree/in_range_options";
import {
    matchInRangeProviderOption,
    resolveInRangeProviderOption,
} from "@web/core/tree/in_range_providers";
export class Input extends Component {
    static props = ["value", "update", "placeholder?", "startEmpty?"];
    static template = "web.TreeEditor.Input";
}

export class Select extends Component {
    static props = [
        "value",
        "update",
        "options",
        "placeholder?",
        "addBlankOption?",
        "optionGroups?",
    ];
    static template = "web.TreeEditor.Select";

    /**
     * The options laid out as the template renders them: the ungrouped ones
     * first, then one `<optgroup>` per group in first-seen order.
     *
     * `optionGroups` maps an option value to its group label. It is a side
     * table rather than a third slot in each option so that every existing
     * caller — all of which pass plain `[value, label]` pairs — keeps working
     * untouched.
     *
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
    static props = ["value", "update", "editorInfo"];
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
    static props = ["value", "update", "valueTypeEditorInfo", "betweenEditorInfo"];
    static template = "web.TreeEditor.InRange";
    static options = IN_RANGE_OPTIONS;

    /**
     * The value type the select should show as picked.
     *
     * A named period from a provider is stored as a plain `custom range` — the
     * two are the same domain, see `@web/core/tree/in_range_providers` — so a
     * stored range is offered back to its period whenever its bounds still name
     * one. When they name none, or the period has since been deleted or moved,
     * this falls back to `custom range` and the two date inputs appear: the
     * condition keeps filtering exactly as it did either way.
     *
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
            // A period is stored as the range it denotes, not as its own value
            // type; picking one is picking its two dates.
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
    static props = ["value", "update", "editorInfo"];
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
