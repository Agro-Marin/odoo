/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { useSubEnv } from "@odoo/owl";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";

patch(ProductConfiguratorDialog.prototype, {
    setup() {
        super.setup(...arguments);

        useSubEnv({
            isQuantityAllowed: this._isQuantityAllowed.bind(this),
        });
    },

    async _setQuantity(productTmplId, quantity) {
        const product = this._findProduct(productTmplId);
        if (!this._isQuantityAllowed(product, quantity)) {
            quantity = product.qty_free;
        }
        return super._setQuantity(productTmplId, quantity);
    },

    /**
     * @param {Object} product
     * @param {Number} quantity
     * @return {Boolean}
     */
    _isQuantityAllowed(product, quantity) {
        return !("qty_free" in product) || product.qty_free >= quantity;
    },

    /**
     * @return {Boolean}
     */
    areQuantitiesAllowed() {
        return this.state.products.every((p) => this._isQuantityAllowed(p, p.quantity));
    },
});
