/** @odoo-module native */
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";
import { patch } from "@web/core/utils/patch";
patch(PosOrderline.prototype, {
    setup(_defaultObj) {
        super.setup(...arguments);
        if (this.sale_order_origin_id?.shipping_date) {
            this.order_id.setShippingDate(this.sale_order_origin_id.shipping_date);
        }
    },
    get saleDetails() {
        const down_payment_details =
            typeof this.down_payment_details === "string"
                ? JSON.parse(this.down_payment_details)
                : this.down_payment_details || [];
        return down_payment_details?.map?.((detail) => ({
            product_qty: detail.product_qty ?? detail.product_uom_qty,
            product_name: detail.product_name,
            total: formatCurrency(detail.total, this.currency),
        }));
    },
    /**
     * @param {'sale.order.line'} saleOrderLine
     */
    async setQuantityFromSOL(saleOrderLine) {
        if (
            this.product_id.type === "service" &&
            this.sale_order_origin_id.state !== "draft"
        ) {
            this.setQuantity(saleOrderLine.qty_to_invoice);
        } else {
            this.setQuantity(
                saleOrderLine.product_uom_qty -
                    Math.max(saleOrderLine.qty_transferred, saleOrderLine.qty_invoiced),
            );
        }
    },
});
