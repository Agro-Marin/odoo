// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/mobile_filter_panel/calendar_mobile_filter_panel - Compact filter panel for mobile calendar with sidebar toggle */

import { Component } from "@odoo/owl";
import { getColor, sortCalendarFilters } from "@web/views/calendar/calendar_utils";

/** Compact filter panel for mobile calendar view with toggle sidebar support. */
export class CalendarMobileFilterPanel extends Component {
    static components = {};
    static template = "web.CalendarMobileFilterPanel";
    static props = {
        model: Object,
        sideBarShown: Boolean,
        toggleSideBar: Function,
    };
    /** @returns {"down" | "left"} caret icon direction based on sidebar visibility */
    get caretDirection() {
        return this.props.sideBarShown ? "down" : "left";
    }
    /**
     * @param {{ colorIndex: number }} filter - calendar filter descriptor
     * @returns {string} CSS color class for the filter badge
     */
    getFilterColor(filter) {
        return `o_color_${getColor(filter.colorIndex)}`;
    }
    /**
     * @param {{ filters: Array<{ type: string, value: any, label: string }> }} section - filter section
     * @returns {Array} filters sorted by type priority, then alphabetically by label
     */
    getSortedFilters(section) {
        // Same priority order as the desktop section (the comparator is
        // shared); the "all" filter type it used to keep last no longer
        // exists.
        return sortCalendarFilters(section.filters, ["user", "record", "dynamic"]);
    }
}
