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

    /** @param {Event} ev */
    onSelected(ev) {
        const target = /** @type {HTMLSelectElement} */ (ev.target);
        if (target.value) {
            this.props.onAddCustomGroup(target.value);
            target.value = "";
        }
    }
}
