// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef } from "@odoo/owl";
import { useDropdownCloser } from "@web/components/dropdown/dropdown_hooks";

/** Adds `o-navigable` to dropdown items (for keyboard nav) and closes the parent dropdown on item click. */
export class KanbanDropdownMenuWrapper extends Component {
    static template = "web.KanbanDropdownMenuWrapper";
    static props = {
        slots: Object,
    };

    setup() {
        this.dropdownControl = useDropdownCloser();
        this.rootRef = useRef("rootRef");
        useEffect(() => {
            const dropdownEls = this.rootRef.el.querySelectorAll(".dropdown-item");
            dropdownEls.forEach((el) => el.classList.add("o-navigable"));
        });
    }

    /** Close all ancestor dropdowns on item click.
     * @param {MouseEvent} ev
     */
    onClick(ev) {
        this.dropdownControl.closeAll();
    }
}
