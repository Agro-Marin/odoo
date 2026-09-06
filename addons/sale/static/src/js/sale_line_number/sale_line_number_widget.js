import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Anchor for the line number drawn on a sales order line.
 *
 * The number itself is a CSS counter (sale_line_number.scss), not a field:
 * dragging a line to another position has to renumber the whole list at once,
 * and a counter does that with no write and no round trip.
 */
export class SaleLineNumberWidget extends Component {
    static template = "sale.SaleLineNumber";
    static props = { ...standardWidgetProps };
}

export const saleLineNumber = {
    component: SaleLineNumberWidget,
    // our <widget> schema takes name/options/width only, so the column cannot
    // carry a column_invisible: the row decides, from the company setting it
    // mirrors through the order
    fieldDependencies: [{ name: "show_sol_numbers", type: "boolean" }],
};

registry.category("view_widgets").add("sale_line_number", saleLineNumber);
