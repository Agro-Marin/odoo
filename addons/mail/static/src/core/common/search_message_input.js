/** @odoo-module native */
import { Component, useExternalListener, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { useAutofocus } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
/**
 * @typedef {Object} SearchFilter
 * @property {string} label
 * @property {string} name
 * @property {true|false|undefined} [is_notification]
 */

/**
 * @typedef {Object} Props
 * @property {ReturnType<typeof import("@mail/core/common/message_search_hook").useMessageSearch>} messageSearch
 * @property {import("models").Thread} thread
 * @property {function} [closeSearch]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */

/**
 * Each keystroke would otherwise be one `/discuss/channel/messages` round trip:
 * `useMessageSearch` serialises them but does not drop any.
 */
export const SEARCH_DEBOUNCE_DELAY = 300;

export class SearchMessageInput extends Component {
    static template = "mail.SearchMessageInput";
    static props = ["closeSearch?", "messageSearch", "thread"];
    static components = { Dropdown, DropdownItem };

    setup() {
        super.setup();
        this.state = useState({ searchTerm: "", searchedTerm: "" });
        this.debouncedSearch = useDebounced(() => this.search(), SEARCH_DEBOUNCE_DELAY);
        useAutofocus();
        useExternalListener(
            browser,
            "keydown",
            /** @param {KeyboardEvent} ev */
            (ev) => {
                if (ev.key === "Escape") {
                    this.props.closeSearch?.();
                }
            },
            { capture: true },
        );
    }

    search() {
        this.props.messageSearch.searchTerm = this.state.searchTerm;
        this.props.messageSearch.search();
        this.state.searchedTerm = this.state.searchTerm;
    }

    /** Drop the results and the term, but stay on the panel. */
    clear() {
        this.debouncedSearch.cancel();
        this.state.searchTerm = "";
        this.state.searchedTerm = this.state.searchTerm;
        this.props.messageSearch.clear();
    }

    onClickClose() {
        this.clear();
        this.props.closeSearch?.();
    }

    onInputSearch() {
        if (!this.state.searchTerm) {
            this.clear();
            return;
        }
        this.debouncedSearch();
    }

    /** @param {KeyboardEvent} ev */
    onKeydownSearch(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        // Enter still means "now", ahead of the debounce.
        this.debouncedSearch.cancel();
        if (!this.state.searchTerm) {
            this.clear();
        } else {
            this.search();
        }
    }

    /** @param {SearchFilter} searchFilter */
    onChangeSearchFilter(searchFilter) {
        if (searchFilter.is_notification !== this.props.messageSearch.is_notification) {
            this.props.messageSearch.is_notification = searchFilter.is_notification;
            this.search();
        }
    }

    /** @returns {SearchFilter[]} */
    get searchFilters() {
        return [
            {
                label: "all",
                name: _t("All"),
                is_notification: undefined,
            },
            {
                label: "conversations",
                name: _t("Conversations"),
                is_notification: false,
            },
            {
                label: "tracked_changes",
                name: _t("Tracked Changes"),
                is_notification: true,
            },
        ];
    }
}
