// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef } from "@odoo/owl";
import { useDropdownCloser } from "@web/components/dropdown/dropdown_hook";

export class KanbanDropdownMenuWrapper extends Component {
    static template = "web.KanbanDropdownMenuWrapper";
    static props = {
        slots: Object,
    };

    /** @type {ReturnType<typeof useDropdownCloser>} */
    dropdownControl;
    /** @type {import("@odoo/owl").Ref} */
    rootRef;

    setup() {
        this.dropdownControl = useDropdownCloser();
        this.rootRef = useRef("rootRef");
        useEffect(() => {
            const dropdownEls = /** @type {HTMLElement[]} */ ([
                ...(this.rootRef.el?.querySelectorAll(".dropdown-item") ?? []),
            ]);
            dropdownEls.forEach((el) => el.classList.add("o-navigable"));
        });
    }

    /**
     * @param {MouseEvent} ev
     */
    onClick(ev) {
        this.dropdownControl.closeAll();
    }
}
