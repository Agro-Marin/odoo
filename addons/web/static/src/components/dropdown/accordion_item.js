// @ts-check
/** @odoo-module native */

import { Component, onPatched, useState } from "@odoo/owl";

/**
 * @typedef AccordionParent
 * @property {(isOpen: boolean) => any} [accordionStateChanged]
 */

export const ACCORDION = Symbol("Accordion");
export class AccordionItem extends Component {
    static template = "web.AccordionItem";
    static props = {
        slots: {
            type: Object,
            shape: {
                default: {},
            },
        },
        description: String,
        selected: {
            type: Boolean,
            optional: true,
        },
        class: {
            type: String,
            optional: true,
        },
    };
    static defaultProps = {
        class: "",
        selected: false,
    };

    /** @type {{ open: boolean }} */
    state;
    /** @type {AccordionParent | undefined} */
    parentComponent;
    /**
     * @type {boolean}
     */
    _reportedOpen;

    setup() {
        this.state = useState({
            open: false,
        });
        this.parentComponent = /** @type {any} */ (this.env)[ACCORDION];
        this._reportedOpen = this.state.open;
        onPatched(() => this.reportStateChange());
    }

    reportStateChange() {
        if (this.state.open === this._reportedOpen) {
            return;
        }
        this._reportedOpen = this.state.open;
        this.parentComponent?.accordionStateChanged?.(this.state.open);
    }
}
