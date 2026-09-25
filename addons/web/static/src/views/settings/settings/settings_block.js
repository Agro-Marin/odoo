// @ts-check
/** @odoo-module native */

import { Component, useRef, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { normalizedMatch } from "@web/core/l10n/utils";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { HighlightText } from "@web/views/settings/highlight_text/highlight_text";
import {
    provideChildSettingsSearchContext,
    useSettingsSearchContext,
} from "@web/views/settings/settings_search_context";

const log = makeLogger("web.views.settings.block");

export class SettingsBlock extends Component {
    static template = "web.SettingsBlock";
    static components = {
        HighlightText,
    };
    static props = {
        title: { type: String, optional: true },
        tip: { type: String, optional: true },
        slots: { type: Object, optional: true },
        class: { type: String, optional: true },
    };
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerRef;
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerTipRef;
    /** @type {import("@odoo/owl").Ref} */
    settingsContainerTitleRef;
    /** @type {{ searchState: any, readonly showAllContainer: boolean }} */
    showAllContainerState;
    /** @type {{ search: any }} */
    state;

    setup() {
        this.settingsContext = useSettingsSearchContext();
        this.state = useState({
            search: this.settingsContext.searchState,
        });
        const block = this;
        this.showAllContainerState = {
            searchState: this.settingsContext.searchState,
            get showAllContainer() {
                const matches = block.matches(this.searchState.value);
                log.logic("showAllContainer", () => ({
                    title: block.props.title,
                    search: this.searchState.value,
                    matches,
                }));
                return matches;
            },
        };
        provideChildSettingsSearchContext({
            showAllContainer: this.showAllContainerState,
        });
        this.settingsContainerRef = useRef("settingsContainer");
        this.settingsContainerTitleRef = useRef("settingsContainerTitle");
        this.settingsContainerTipRef = useRef("settingsContainerTip");
        useLayoutEffect(
            () => {
                const container = this.settingsContainerRef.el;
                if (!container) {
                    return;
                }
                const force =
                    this.state.search.value &&
                    !this.matchesTitleOrTip() &&
                    !container.querySelector(".o_setting_box.o_searchable_setting");
                this.toggleContainer(force);
            },
            () => [this.state.search.value],
        );
    }
    /** @returns {boolean} */
    matchesTitleOrTip() {
        return this.matches(this.state.search.value);
    }
    /**
     * @param {string} searchValue
     * @returns {boolean}
     */
    matches(searchValue) {
        const blockText = [this.props.title, this.props.tip].join();
        return normalizedMatch(blockText, searchValue).start !== -1;
    }
    /** @param {boolean} force */
    toggleContainer(force) {
        if (this.settingsContainerTitleRef.el) {
            this.settingsContainerTitleRef.el.classList.toggle("d-none", force);
        }
        if (this.settingsContainerTipRef.el) {
            this.settingsContainerTipRef.el.classList.toggle("d-none", force);
        }
        this.settingsContainerRef.el?.classList.toggle("d-none", force);
    }
}
