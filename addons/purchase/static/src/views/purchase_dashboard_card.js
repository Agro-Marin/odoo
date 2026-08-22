/** @odoo-module native */
import { Component } from "@odoo/owl";

/**
 * One count card of the purchase dashboard.
 *
 * The "All" and "My" rows render the same component with a different scope, so
 * the two can no longer drift apart — the "My Days to Order" card used to be
 * coloured by the *global* average because its markup was a hand-copied twin.
 */
export class PurchaseDashboardCard extends Component {
    static template = "purchase.PurchaseDashboardCard";
    static props = {
        /** caption under the figure; the "my" row is unlabelled (the row is) */
        label: { type: String, optional: true },
        /** `title` attribute, already scoped ("My Late RFQs") */
        title: String,
        /** bootstrap colour name used when the count is non-zero */
        emphasis: String,
        /** `{ all, priority }` for this bucket */
        values: Object,
        /** "top" | "bottom" | "sole" — which corners are rounded */
        position: String,
        onSelected: Function,
    };

    get colorClass() {
        // A zero count is never emphasised: the card is informational, not a
        // call to action, and colouring an empty bucket reads as a false alarm.
        const emphasis = this.props.values.all ? this.props.emphasis : "secondary";
        return `bg-${emphasis}-subtle text-${emphasis}-emphasis`;
    }
}
