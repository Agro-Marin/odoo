/** @odoo-module native */
// Little class to manage the refund of a line
// This will be also usefull when needed to save
// the refund in indexedDB
export class PosOrderLineRefund {
    constructor() {
        this.setup(...arguments);
    }

    setup(vals, models) {
        this.line_uuid = vals.line_uuid || false;
        this.destination_order_uuid = vals.destination_order_uuid || false;
        this.qty = vals.qty || 0;

        this.models = models;
    }

    get line() {
        if (!this.line_uuid) {
            return false;
        }

        return this.models["pos.order.line"].find((l) => l.uuid === this.line_uuid);
    }

    get destinationOrder() {
        if (!this.destination_order_uuid) {
            return false;
        }

        return this.models["pos.order"].find(
            (o) => o.uuid === this.destination_order_uuid,
        );
    }

    get maxQty() {
        if (!this.line) {
            return 0;
        }

        const line = this.line;
        // `refundedQty` lives on the order line, not on this refund detail — reading
        // `this.refundedQty` yielded `undefined`, so maxQty was NaN and the one-tap
        // refund default (`qty = 1` for a single-available-unit line) never fired.
        return line.qty - line.refundedQty;
    }
}
