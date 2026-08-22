// @ts-check
/** @odoo-module native */

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

    /** @type {string[]} */
    visibleButtons;
    /** @type {string[]} */
    additionalButtons;
    /** @type {boolean} */
    isFull;

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
     * @param {{ isVisible?: boolean }} slot
     * @returns {boolean}
     */
    isSlotVisible(slot) {
        return !("isVisible" in slot) || Boolean(slot.isVisible);
    }

    /**
     * @param {MouseEvent} ev
     */
    activateStatButton(ev) {
        const item = /** @type {HTMLElement} */ (ev.currentTarget);
        /** @type {HTMLElement | null} */ (
            item.querySelector(".oe_stat_button")
        )?.click();
    }
}
