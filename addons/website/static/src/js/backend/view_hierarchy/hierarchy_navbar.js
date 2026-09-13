/** @odoo-module native */
import { Component, useRef, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.backend.hierarchy_navbar");

export class HierarchyNavbar extends Component {
    static template = "website.hierarchy_navbar";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        toggleInactive: Function,
        websites: Object,
        selectWebsite: Function,
        searchView: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.searchInput = useRef("search");
        this.websiteNamesState = useState(Array.from(this.props.websites.names));
    }

    get websiteNames() {
        return this.websiteNamesState.map((websiteName) => ({
            label: websiteName,
            onSelected: () => this.props.selectWebsite(websiteName),
        }));
    }

    /**
     * @param {Event} event
     */
    onInputKeydown(event) {
        if (event.key === "Enter" || event.key === "Tab") {
            log.logic("onInputKeydown: search", () => ({
                key: event.key,
                keyword: event.target.value,
                forward: !event.shiftKey,
            }));
            event.preventDefault();
            this.props.searchView(event.target.value, !event.shiftKey);
        }
    }

    /**
     * @param {Event} event
     */
    onInputClick(event) {
        log.logic("onInputClick: search", () => ({ forward: !event.shiftKey }));
        this.props.searchView(this.searchInput.el.value, !event.shiftKey);
    }
}
