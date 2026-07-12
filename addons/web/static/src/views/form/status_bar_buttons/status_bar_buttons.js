// @ts-check
/** @odoo-module native */

/** @module @web/views/form/status_bar_buttons/status_bar_buttons - Renders action buttons in the form status bar with overflow dropdown */

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
export class StatusBarButtons extends Component {
    static template = "web.StatusBarButtons";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        slots: { type: Object, optional: 1 },
    };

    /** @returns {string[]} names of slots whose `isVisible` flag is true */
    get visibleSlotNames() {
        if (!this.props.slots) {
            return [];
        }
        return Object.entries(this.props.slots)
            .filter(
                // A slot with no ``isVisible`` key is visible by default: absence
                // of the modifier means "always show". Treating a missing key as
                // false silently dropped such slots (the header compiler defaults
                // ``isVisible`` to "true", but out-of-tree callers may omit it).
                // Mirrors the exact predicate already fixed in InnerGroup.getRows
                // and ButtonBox.
                ([, slot]) => !("isVisible" in slot) || slot.isVisible,
            )
            .map((entry) => entry[0]);
    }
}
