// @ts-check
/** @odoo-module native */

/** @module @web/components/tree_editor/tree_editor_components */

import { Component } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list/tags_list";
import { IN_RANGE_OPTIONS } from "@web/core/tree/in_range_options";
export class Input extends Component {
    static props = ["value", "update", "placeholder?", "startEmpty?"];
    static template = "web.TreeEditor.Input";
}

export class Select extends Component {
    static props = ["value", "update", "options", "placeholder?", "addBlankOption?"];
    static template = "web.TreeEditor.Select";

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
     * @param {string} newValueType
     */
    updateValueType(newValueType) {
        const [fieldType, currentValueType] = this.props.value;
        if (currentValueType !== newValueType) {
            const values =
                newValueType === "custom range"
                    ? this.props.betweenEditorInfo.defaultValue()
                    : [false, false];
            return this.props.update([fieldType, newValueType, ...values]);
        }
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
