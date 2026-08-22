// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
export class ReportViewMeasures extends Component {
    static template = "web.ReportViewMeasures";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        measures: { type: Object },
        activeMeasures: { type: Array },
        onMeasureSelected: { type: Function },
    };
}
