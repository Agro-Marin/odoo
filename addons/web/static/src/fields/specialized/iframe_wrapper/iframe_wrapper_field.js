// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/iframe_wrapper/iframe_wrapper_field */

import { Component, useEffect, useRef } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class IframeWrapperField extends Component {
    static template = "web.IframeWrapperField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.iframeRef = useRef("iframe");

        useEffect(
            (value) => {
                const iframeDoc = /** @type {HTMLIFrameElement} */ (this.iframeRef.el)
                    .contentDocument;
                iframeDoc.open();
                iframeDoc.write(value || "");
                iframeDoc.close();
            },
            () => [this.props.record.data[this.props.name]],
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const iframeWrapperField = {
    component: IframeWrapperField,
    displayName: _t("Wrap raw html within an iframe"),
    supportedTypes: ["text", "html"],
};

registerField("iframe_wrapper", iframeWrapperField);
