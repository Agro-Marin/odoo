/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useProductCatalogContext } from "@product/product_catalog/product_catalog_context";
import { formatFieldFloat, formatMonetary } from "@web/core/formatters";
import { Portal } from "@web/core/utils/owl_bridge";

export const productCatalogOrderLineProps = {
    isSample: { type: Boolean, optional: true },
    productId: Number,
    quantity: Number,
    price: Number,
    productType: String,
    uomDisplayName: String,
    uomFactor: { type: Number, optional: true },
    code: { type: String, optional: true },
    readOnly: { type: Boolean, optional: true },
    warning: { type: String, optional: true },
};

export class ProductCatalogOrderLine extends Component {
    static template = "product.ProductCatalogOrderLine";
    static components = { Portal };
    static props = productCatalogOrderLineProps;

    setup() {
        super.setup();
        this.catalogContext = useProductCatalogContext();
    }

    /**
     * Focus input text when clicked
     * @param {Event} ev
     */
    _onFocus(ev) {
        ev.target.select();
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    isInOrder() {
        return this.props.quantity !== 0;
    }

    get disableRemove() {
        return false;
    }

    get disabledButtonTooltip() {
        return "";
    }

    get price() {
        const { currencyId, digits } = this.env;
        return formatMonetary(this.props.price, { currencyId, digits });
    }

    get quantity() {
        const digits = [false, this.catalogContext.precision];
        const options = { digits, decimalPoint: ".", thousandsSep: "" };
        return parseFloat(formatFieldFloat(this.props.quantity, options));
    }

    get showPrice() {
        return true;
    }
}
