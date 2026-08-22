// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { SearchPanel } from "@web/search/search_panel/search_panel";

/**
 * @param {Record<string, any>} params
 * @returns {Record<string, any>}
 */
export function extractLayoutComponents(params) {
    const layoutComponents = {
        ControlPanel: params.ControlPanel || ControlPanel,
        SearchPanel: params.SearchPanel || SearchPanel,
    };
    return layoutComponents;
}

export class Layout extends Component {
    static template = "web.Layout";
    static props = {
        className: { type: String, optional: true },
        display: { type: Object, optional: true },
        slots: { type: Object, optional: true },
    };
    static defaultProps = {
        display: {},
    };
    setup() {
        this.components = extractLayoutComponents(this.env.config);
        this.contentRef = useRef("content");
    }
    /** @returns {Record<string, any>} */
    get controlPanelSlots() {
        const slots = { ...this.props.slots };
        if (this.env.inDialog) {
            delete slots["layout-buttons"];
        }
        delete slots.default;
        return slots;
    }
}
