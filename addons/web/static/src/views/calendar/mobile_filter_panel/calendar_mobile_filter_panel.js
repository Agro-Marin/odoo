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
        // Mobile keeps "all" last in its priority order (unlike the desktop
        // section, which omits it); the comparator itself is shared.
        return sortCalendarFilters(section.filters, [
            "user",
            "record",
            "dynamic",
            "all",
        ]);
    }
}
