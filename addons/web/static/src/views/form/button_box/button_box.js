// @ts-check
/** @odoo-module native */

/** @module @web/views/form/button_box/button_box - Responsive stat-button container with overflow dropdown for form views */

import { Component, onWillRender } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";

export class ButtonBox extends Component {
    static template = "web.Form.ButtonBox";
    static components = { Dropdown, DropdownItem };
    static props = {
        slots: Object,
        class: { type: String, optional: true },
    };
    static defaultProps = {
        class: "",
    };

    setup() {
        const ui = useService("ui");
        onWillRender(() => {
            const maxVisibleButtons = [0, 0, 4, 5, 7, 8][ui.size] ?? 8;
            const allVisibleButtons = Object.entries(this.props.slots)
                .filter(([_, slot]) => this.isSlotVisible(slot))
                .map(([slotName]) => slotName);
            if (allVisibleButtons.length <= maxVisibleButtons) {
                this.visibleButtons = allVisibleButtons;
                this.additionalButtons = [];
                this.isFull = allVisibleButtons.length === maxVisibleButtons;
            } else {
                const splitIndex = Math.max(maxVisibleButtons - 1, 0);
                this.visibleButtons = allVisibleButtons.slice(0, splitIndex);
                this.additionalButtons = allVisibleButtons.slice(splitIndex);
                this.isFull = true;
            }
        });
    }

    /**
     * @param {{ isVisible?: boolean }} slot - slot descriptor from props.slots
     * @returns {boolean} whether the slot should be rendered
     */
    isSlotVisible(slot) {
        return !("isVisible" in slot) || slot.isVisible;
    }

    /**
     * Selection handler for an overflow ("More") DropdownItem.
     *
     * Each additional stat button is a self-contained ViewButton that owns its
     * own action AND closes the dropdown (via its onClick's beforeExecute). The
     * wrapping DropdownItem's onClick stops at ``onSelected`` + closeAll, so it
     * only ever wins the click when the pointer resolves to the wrapper rather
     * than the inner button — which happens on touch (notably Android Chrome),
     * where the resulting "sheet closes, no action" is the whole bug. Forward
     * the selection to the wrapped button so activating the row anywhere runs
     * the action. A direct hit on the button stops propagation before reaching
     * here, so there is no double activation.
     *
     * @param {MouseEvent} ev - click event from the DropdownItem
     */
    activateStatButton(ev) {
        const item = /** @type {HTMLElement} */ (ev.currentTarget);
        /** @type {HTMLElement | null} */ (
            item.querySelector(".oe_stat_button")
        )?.click();
    }
}
