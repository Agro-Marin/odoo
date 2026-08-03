// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/json/json_field */

import { Component } from "@odoo/owl";
import { formatJson } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JsonField extends Component {
    static template = "web.JsonField";
    static props = {
        ...standardFieldProps,
    };
    /** @returns {string} */
    get formattedValue() {
        return formatJson(this.props.record.data[this.props.name]);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const jsonField = {
    component: JsonField,
    displayName: _t("Json"),
    supportedTypes: ["json"],
};

registerField("json", jsonField);
