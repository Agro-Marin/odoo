/** @odoo-module native */
import { Component, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/fields/formatters";

export class ForecastedHeader extends Component {
    static template = "stock.ForecastedHeader";
    static props = { docs: Object, openView: Function };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this._formatFloat = (num) =>
            formatFloat(num, { digits: [false, this.props.docs.precision] });
        // Computed once; leadTime is read several times per render and previously
        // rebuilt dates and mutated the report data on every access.
        this.leadTimeData = this._computeLeadTime();
    }

    async _onClickInventory() {
        const productIds = this.props.docs.product_variants_ids;
        const action = await this.orm.call("product.product", "action_view_quants", [
            productIds,
        ]);
        if (action.help) {
            action.help = markup(action.help);
        }
        return this.action.doAction(action);
    }

    get products() {
        return this.props.docs.product;
    }

    get leadTime() {
        return this.leadTimeData;
    }

    _computeLeadTime() {
        const productsArray = Object.values(this.products || {});
        if (!productsArray.length) {
            return null;
        }
        const product = productsArray.reduce((minProduct, p) => {
            if (
                !minProduct ||
                (p.leadtime &&
                    p.leadtime.total_delay <
                        (minProduct.leadtime?.total_delay ?? Infinity))
            ) {
                return p;
            }
            return minProduct;
        }, null);
        if (!product?.leadtime) {
            return null;
        }
        // Return a derived copy; never write today/earliestPossibleArrival back
        // into the shared report data.
        const today = new Date();
        return {
            ...product.leadtime,
            today: today.toLocaleDateString(),
            earliestPossibleArrival: this.addDays(today, product.leadtime.total_delay),
        };
    }

    get leadTimeShort() {
        let short = " " + this.leadTime.total_delay + " day(s)";
        if (this.leadTime.total_delay !== 0) {
            short += " (" + this.leadTime.earliestPossibleArrival + ")";
        }
        return short;
    }

    get quantityOnHand() {
        return Object.values(this.products).reduce(
            (sum, product) => sum + product.quantity_on_hand,
            0,
        );
    }

    get incomingQty() {
        return Object.values(this.products).reduce(
            (sum, product) => sum + product.qty_incoming,
            0,
        );
    }

    get outgoingQty() {
        return Object.values(this.products).reduce(
            (sum, product) => sum + product.qty_outgoing,
            0,
        );
    }

    get virtualAvailable() {
        return Object.values(this.products).reduce(
            (sum, product) => sum + product.qty_available_virtual,
            0,
        );
    }

    get uom() {
        return Object.values(this.products)[0].uom;
    }

    addDays(date, days) {
        const result = new Date(date);
        result.setDate(result.getDate() + days);
        return result.toLocaleDateString();
    }

    toJsonString(obj) {
        return JSON.stringify(obj);
    }
}
