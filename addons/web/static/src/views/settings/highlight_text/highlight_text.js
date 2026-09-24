// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { highlightText } from "@web/core/utils/dom/html";
import { useSettingsSearchContext } from "@web/views/settings/settings_search_context";
export class HighlightText extends Component {
    static template = "web.HighlightText";
    static props = {
        originalText: String,
    };
    /** @type {any} */
    searchState;

    setup() {
        this.settingsContext = useSettingsSearchContext();
        /** @type {{ value: string }} */
        this.searchState = useState(this.settingsContext.searchState);
    }

    /** @returns {string | import("@odoo/owl").Markup} */
    get text() {
        return highlightText(
            this.searchState.value,
            this.props.originalText,
            "highlighter",
        );
    }
}
