// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/settings/searchable_setting - Setting variant with search-based visibility filtering and URL hash highlighting */

import { onMounted, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { normalizedMatch } from "@web/core/l10n/utils";
import { Setting } from "@web/views/form/setting/setting";
import { FormLabelHighlightText } from "@web/views/settings/highlight_text/form_label_highlight_text";
import { HighlightText } from "@web/views/settings/highlight_text/highlight_text";

export class SearchableSetting extends Setting {
    static template = "web.SearchableSetting";
    static components = {
        ...Setting.components,
        FormLabel: FormLabelHighlightText,
        HighlightText,
    };
    /**
     * Initialize search state, collect searchable label texts, and apply
     * URL-hash-based highlight animation on mount.
     */
    setup() {
        this.settingRef = useRef("setting");
        /** @type {{ search: { value: string }, showAllContainer: { showAllContainer: boolean }, highlightClass: Record<string, boolean> }} */
        this.state = useState({
            search: this.env.searchState,
            showAllContainer: this.env.showAllContainer,
            highlightClass: {},
        });
        this.labels = [];
        this.labels.push(this.labelString, this.props.help);
        super.setup();
        onMounted(() => {
            if (this.settingRef.el) {
                const searchableTexts =
                    this.settingRef.el.querySelectorAll("span[searchableText]");
                searchableTexts.forEach((st) => {
                    this.labels.push(st.getAttribute("searchableText"));
                });
            }
            if (browser.location.hash.slice(1) === this.props.id) {
                this.state.highlightClass = { o_setting_highlight: true };
                browser.setTimeout(() => (this.state.highlightClass = {}), 5000);
            }
        });
    }

    /**
     * CSS class map extended with searchable and highlight classes.
     * @returns {Record<string, boolean>}
     */
    get classNames() {
        const classNames = super.classNames;
        classNames.o_searchable_setting = Boolean(this.labels.length);
        return { ...classNames, ...this.state.highlightClass };
    }

    /**
     * Whether this setting matches the current search, or true if there is
     * no search or "show all" is active.
     * @returns {boolean}
     */
    visible() {
        if (!this.state.search.value) {
            return true;
        }
        if (this.state.showAllContainer.showAllContainer) {
            return true;
        }
        if (normalizedMatch(this.labels.join(), this.state.search.value).match) {
            return true;
        }
        return false;
    }
}
