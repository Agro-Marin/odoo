// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/iframe_wrapper/iframe_wrapper_field - Iframe wrapper that renders HTML field content inside an isolated iframe */

import { Component, useEffect, useRef } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
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
                // document.write over DOM methods: this iframe has no src, so the
                // usual appendChild approach would need head/body metadata fed in
                // piece by piece (extra record data or RPCs); write() sets the
                // full document in one call.
                const iframeDoc = /** @type {HTMLIFrameElement} */ (this.iframeRef.el)
                    .contentDocument;
                iframeDoc.open();
                iframeDoc.write(value);
                iframeDoc.close();
            },
            () => [this.props.record.data[this.props.name]],
        );
    }
}

export const iframeWrapperField = {
    component: IframeWrapperField,
    displayName: _t("Wrap raw html within an iframe"),
    // If HTML, don't forget to adjust the sanitize options to avoid stripping most of the metadata
    supportedTypes: ["text", "html"],
};

registerField("iframe_wrapper", iframeWrapperField);
