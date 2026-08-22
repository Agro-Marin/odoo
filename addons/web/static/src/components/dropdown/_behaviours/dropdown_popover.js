// @ts-check
/** @odoo-module native */

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
        close: { type: Function, optional: true },

        beforeOpen: { type: Function, optional: true },
        onOpened: { type: Function, optional: true },
        onClosed: { type: Function, optional: true },

        refresher: Object,
        slots: Object,
        items: { type: Array, optional: true },
    };

    setup() {
        onRendered(() => {
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
     * @param {Record<string, any>} item
     * @param {number} index
     * @returns {string | number}
     */
    getKey(item, index) {
        return "id" in item ? item.id : index;
    }
}
