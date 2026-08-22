/** @odoo-module native */
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";

/**
 * Catalog order line for a purchase order.
 *
 * The base card is rendered with `t-props="productCatalogData"`, i.e. the whole
 * server dict becomes the component's props — so every key purchase's
 * `_get_product_price_and_data` may add needs a declaration here, or OWL prop
 * validation rejects the card in dev mode.
 */
export class ProductCatalogPurchaseOrderLine extends ProductCatalogOrderLine {
    static props = {
        ...ProductCatalogOrderLine.props,
        min_qty: { type: Number, optional: true },
    };
}
