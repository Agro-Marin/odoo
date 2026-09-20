/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
const log = makeLogger("pos.refund");
export class PosOrderLineRefund {
    constructor() {
        this.setup(...arguments);
    }

    setup(vals, models) {
        this.line_uuid = vals.line_uuid || false;
        this.destination_order_uuid = vals.destination_order_uuid || false;
        this.qty = vals.qty || 0;

        this.models = models;
        log.lifecycle("setup", () => ({
            line: this.line_uuid,
            destination: this.destination_order_uuid,
            qty: this.qty,
        }));
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
        return line.qty - line.refundedQty;
    }
}
