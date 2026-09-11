/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Product } from "@sale/js/product/product";

patch(Product, {
    props: {
        ...Product.props,
        qty_free: { type: Number, optional: true },
    },
});

patch(Product.prototype, {
    /**
     * @return {Boolean}
     */
    isOutOfStock() {
        return !this.env.isQuantityAllowed(this.props, 1);
    },
});
