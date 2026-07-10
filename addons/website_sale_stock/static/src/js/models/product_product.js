/** @odoo-module native */
import { patch } from '@web/core/utils/patch';
import { ProductProduct } from '@sale/js/models/product_product';

patch(ProductProduct.prototype, {
    /**
     * @param {number} qty_free
     * @param args Super's parameter list.
     */
    setup({qty_free, ...args}) {
        super.setup(args);
        this.qty_free = qty_free;
    },

    /**
     * Check whether the provided quantity can be added to the cart.
     *
     * @param {Number} quantity The quantity to check.
     * @return {Boolean} Whether the product quantity can be added to the cart.
     */
    isQuantityAllowed(quantity) {
        return this.qty_free === undefined || this.qty_free >= quantity;
    },
});
