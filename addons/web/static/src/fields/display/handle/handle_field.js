// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class HandleField extends Component {
    static template = "web.HandleField";
    static props = {
        ...standardFieldProps,
    };
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const handleField = {
    component: HandleField,
    displayName: _t("Handle"),
    supportedTypes: ["integer"],
    isEmpty: () => false,
    listViewWidth: 20,
    interactiveOutsideEdition: true,
};

registerField("handle", handleField);
