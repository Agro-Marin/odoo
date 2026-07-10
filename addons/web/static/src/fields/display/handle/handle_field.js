// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/handle/handle_field - Drag handle icon for manual record reordering in list views */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class HandleField extends Component {
    static template = "web.HandleField";
    static props = {
        ...standardFieldProps,
    };
}

export const handleField = {
    component: HandleField,
    displayName: _t("Handle"),
    supportedTypes: ["integer"],
    isEmpty: () => false,
    listViewWidth: 20,
    extractProps(_, dynamicInfo) {
        return {
            readonly: dynamicInfo.readonly,
        };
    },
};

registerField("handle", handleField);
