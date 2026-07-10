// @ts-check
/** @odoo-module native */

/** @module @web/search/custom_group_by_item/custom_group_by_item - Dropdown item for selecting a custom field to group by */

import { Component } from "@odoo/owl";

export class CustomGroupByItem extends Component {
    static template = "web.CustomGroupByItem";
    static props = {
        fields: Array,
        onAddCustomGroup: Function,
    };

    /** @returns {Array<{label: string, value: string}>} */
    get choices() {
        return this.props.fields.map((f) => ({
            label: f.string,
            value: f.name,
        }));
    }

    /** @param {Event} ev */
    onSelected(ev) {
        const target = /** @type {HTMLSelectElement} */ (ev.target);
        if (target.value) {
            this.props.onAddCustomGroup(target.value);
            // reset the placeholder
            target.value = "";
        }
    }
}
