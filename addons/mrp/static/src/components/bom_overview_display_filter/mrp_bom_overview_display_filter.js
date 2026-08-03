/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";

export class BomOverviewDisplayFilter extends Component {
    static template = "mrp.BomOverviewDisplayFilter";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        showOptions: {
            type: Object,
        },
        changeDisplay: Function,
    };

    setup() {
        this.displayOptions = {};
    }

    //---- Getters ----

    get displayableOptions() {
        return Object.keys(this.displayOptions).map((optionKey) => ({
            id: optionKey,
            label: this.displayOptions[optionKey],
            onSelected: () => this.props.changeDisplay(optionKey),
            class: { o_menu_item: true, selected: this.props.showOptions[optionKey] },
            closingMode: "none",
        }));
    }
}
