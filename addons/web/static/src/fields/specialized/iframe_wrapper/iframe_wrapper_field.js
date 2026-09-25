// @ts-check
/** @odoo-module native */

import { useRef } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class IframeWrapperField extends FieldComponent {
    static template = "web.IframeWrapperField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.iframeRef = useRef("iframe");

        useLayoutEffect(
            (value) => {
                const iframeDoc = /** @type {HTMLIFrameElement} */ (this.iframeRef.el)
                    .contentDocument;
                iframeDoc.open();
                iframeDoc.write(value || "");
                iframeDoc.close();
            },
            () => [this.field.value],
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const iframeWrapperField = {
    component: IframeWrapperField,
    displayName: _t("Wrap raw html within an iframe"),
    supportedTypes: ["text", "html"],
};

registerField("iframe_wrapper", iframeWrapperField);
