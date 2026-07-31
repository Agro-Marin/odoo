// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/highlight_text/highlight_text */

import { Component, onWillRender, useState } from "@odoo/owl";
import { highlightText } from "@web/core/utils/dom/html";
export class HighlightText extends Component {
    static template = "web.HighlightText";
    static props = {
        originalText: String,
    };
    /** @type {any} */
    searchState;

    setup() {
        /** @type {{ value: string }} */
        this.searchState = useState(this.env.searchState);

        onWillRender(() => {
            /** @type {string | import("@odoo/owl").Markup} */
            this.text = highlightText(
                this.searchState.value,
                this.props.originalText,
                "highlighter",
            );
        });
    }
}
