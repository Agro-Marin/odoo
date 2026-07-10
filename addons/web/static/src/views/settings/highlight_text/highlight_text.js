// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/highlight_text/highlight_text - Component rendering text with the current search term highlighted via markup */

import { Component, onWillRender, useState } from "@odoo/owl";
import { highlightText } from "@web/core/utils/dom/html";
export class HighlightText extends Component {
    static template = "web.HighlightText";
    static props = {
        originalText: String,
    };
    /**
     * Subscribe to env search state and recompute highlighted markup before each render.
     */
    setup() {
        /** @type {{ value: string }} */
        this.searchState = useState(this.env.searchState);

        onWillRender(() => {
            // ``highlightText`` returns the original string when no highlight
            // anchors are inserted (search term empty) and a Markup instance
            // otherwise. The template handles both via ``t-out``.
            /** @type {string | import("@odoo/owl").Markup} */
            this.text = highlightText(
                this.searchState.value,
                this.props.originalText,
                "highlighter",
            );
        });
    }
}
