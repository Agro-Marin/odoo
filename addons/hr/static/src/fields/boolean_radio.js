/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { RadioField, radioField } from "@web/fields/selection/radio/radio_field";
import { onMounted } from "@odoo/owl";

export class BooleanRadio extends RadioField {
    static props = {
        ...RadioField.props,
        yes_label_element_id: { type: String },
        no_label_element_id: { type: String },
    };
    setup() {
        super.setup(...arguments);
        onMounted(this.moveElement);
    }

    moveElement() {
        // Guard every lookup: the label source elements may be absent (hidden by
        // `invisible=`, which removes them from the DOM, or a mistyped option id),
        // in which case `getElementById` returns null and `.innerText` would throw
        // and take down the whole form render.
        // NB: the `[data-value=...]` query is document-wide; with two boolean_radio
        // widgets on one view the first match wins. Kept as-is (single-instance use).
        const setLabel = (value, sourceId) => {
            const input = document.querySelector(`[data-value='${value}']`);
            const source = sourceId && document.getElementById(sourceId);
            const label = input?.labels?.[0];
            if (label && source) {
                label.textContent = source.innerText;
            }
        };
        setLabel("true", this.props.yes_label_element_id);
        setLabel("false", this.props.no_label_element_id);
    }

    get items() {
        if (this.type === "boolean") return [["true", ""], ["false", ""]];
        return super.items;
    }

    get value() {
        if (this.type === "boolean") return this.props.record.data[this.props.name].toString();
        return super.value;
    }

    /**
     * @param {any} value
     */
    onChange(value) {
        if (this.type === "boolean") this.props.record.update({ [this.props.name]: value[0] === "true" });
        super.onChange();
    }

}

export const booleanRadio = {
    ...radioField,
    component: BooleanRadio,
    displayName: _t("Boolean display as radio field with translatable labels"),
    supportedOptions: [
        {
            label: _t("True association"),
            name: "yes_label_element_id",
            type: "string",
            help: _t("Link an element with the boolean True value."),
        },
        {
            label: _t("False association"),
            name: "no_label_element_id",
            type: "string",
            help: _t("Link an element with the boolean False value."),
        },
    ],
    supportedTypes: ["boolean"],
    extractProps({ options }, dynamicInfo) {
        return {
            readonly: dynamicInfo.readonly,
            yes_label_element_id: options.yes_label_element_id,
            no_label_element_id: options.no_label_element_id,
        };
    },
};

registry.category("fields").add("boolean_radio", booleanRadio);
