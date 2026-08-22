/** @odoo-module native */
import { Component } from "@odoo/owl";

export class PurchaseDashboardCard extends Component {
    static template = "purchase.PurchaseDashboardCard";
    static props = {
        label: { type: String, optional: true },
        title: String,
        emphasis: String,
        values: Object,
        position: String,
        onSelected: Function,
    };

    get colorClass() {
        const emphasis = this.props.values.all ? this.props.emphasis : "secondary";
        return `bg-${emphasis}-subtle text-${emphasis}-emphasis`;
    }
}
