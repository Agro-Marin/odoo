// @ts-check
/** @odoo-module native */

/** @module @web/views/view_components/report_view_measures - Dropdown selector for choosing numeric measures in pivot/graph report views */

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
