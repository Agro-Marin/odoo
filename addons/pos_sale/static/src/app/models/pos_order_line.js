/** @odoo-module native */
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";
import { patch } from "@web/core/utils/patch";
patch(PosOrderline.prototype, {
    setup(_defaultObj) {
        super.setup(...arguments);
        // It is possible that this orderline is initialized using server data,
        // meaning, it is loaded from localStorage or from server. This means
        // that some fields has already been assigned. Therefore, we only set the options
        // when the original value is falsy.
        if (this.sale_order_origin_id?.shipping_date) {
            this.order_id.setShippingDate(this.sale_order_origin_id.shipping_date);
        }
    },
    get orderDisplayProductName() {
        if (this.has_default_product && this.sale_order_line_id) {
            return {
                name: this.sale_order_line_id.name,
                attributeString: "",
            };
        }
        return super.orderDisplayProductName;
    },
    get saleDetails() {
        const down_payment_details =
            typeof this.down_payment_details === "string"
                ? JSON.parse(this.down_payment_details)
                : this.down_payment_details || [];
        return down_payment_details?.map?.((detail) => ({
            product_uom_qty: detail.product_uom_qty,
            product_name: detail.product_name,
            total: formatCurrency(detail.total, this.currency),
        }));
    },
    /**
     * Set quantity based on the give sale order line.
     * @param {'sale.order.line'} saleOrderLine
     */
    async setQuantityFromSOL(saleOrderLine) {
        if (
            this.product_id.type === "service" &&
            !["sent", "draft"].includes(this.sale_order_origin_id.state)
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
