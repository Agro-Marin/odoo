// @ts-check
/** @odoo-module native */

import { onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
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

    /** @type {string[]} */
    labels;

    setup() {
        this.settingRef = useRef("setting");
        /**
         * @type {{ search: { value: string }, showAllContainer: { showAllContainer: boolean }, highlightClass: Record<string, boolean> }}
         */
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
                this._highlightTimer = browser.setTimeout(
                    () => (this.state.highlightClass = {}),
                    5000,
                );
            }
        });
        onWillUnmount(() => browser.clearTimeout(this._highlightTimer));
    }

    /**
     * @returns {Record<string, boolean>}
     */
    get classNames() {
        const classNames = super.classNames;
        classNames.o_searchable_setting = Boolean(this.labels.length);
        return { ...classNames, ...this.state.highlightClass };
    }

    /**
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
