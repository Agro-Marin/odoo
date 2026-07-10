// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/_behaviours/dropdown_popover - Popover content renderer for dropdown menus with item list and slot support */

import {
    Component,
    onMounted,
    onRendered,
    onWillDestroy,
    onWillStart,
    xml,
} from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";

export class DropdownPopover extends Component {
    static components = { DropdownItem };
    static template = xml`
        <t t-if="this.props.items">
            <t t-foreach="this.props.items" t-as="item" t-key="this.getKey(item, item_index)">
                <DropdownItem class="item.class" onSelected="() => item.onSelected()" t-out="item.label"/>
            </t>
        </t>
        <t t-slot="content" />
    `;
    static props = {
        // Popover service
        close: { type: Function, optional: true },

        // Events & Handlers
        beforeOpen: { type: Function, optional: true },
        onOpened: { type: Function, optional: true },
        onClosed: { type: Function, optional: true },

        // Rendering & Context
        refresher: Object,
        slots: Object,
        items: { type: Array, optional: true },
    };

    setup() {
        onRendered(() => {
            // Dropdown and DropdownPopover are separate contexts; subscribe to
            // this reactive so we re-render whenever Dropdown does.
            this.props.refresher.token;
        });

        onWillStart(async () => {
            await this.props.beforeOpen?.();
        });

        onMounted(() => {
            this.props.onOpened?.();
        });

        onWillDestroy(() => {
            this.props.onClosed?.();
        });
    }

    /**
     * @param {Object} item - dropdown item, may have an `id` property
     * @param {number} index - positional index used as fallback key
     * @returns {string | number} unique key for the item
     */
    getKey(item, index) {
        return "id" in item ? item.id : index;
    }
}
