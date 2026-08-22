/** @odoo-module native */
import { Component, onWillStart, useState, useSubEnv } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { KeepLast } from "@web/core/utils/concurrency";
import { Dialog } from "@web/ui/dialog";

import { ProductList } from "../product_list/product_list.js";
import {
    checkExclusions,
    findProduct,
    getChildProducts,
    getCombination,
    getParentsCombination,
    getVariantCombination,
    isPossibleCombination,
} from "./product_configurator_utils.js";

export class ProductConfiguratorDialog extends Component {
    static components = { Dialog, ProductList };
    static template = "sale.ProductConfiguratorDialog";
    static props = {
        productTemplateId: Number,
        ptavIds: { type: Array, element: Number },
        customPtavs: {
            type: Array,
            element: Object,
            shape: {
                id: Number,
                value: String,
            },
        },
        quantity: Number,
        productUOMId: { type: Number, optional: true },
        companyId: { type: Number, optional: true },
        pricelistId: { type: Number, optional: true },
        currencyId: { type: Number, optional: true },
        selectedComboItems: {
            type: Array,
            element: Object,
            shape: {
                name: String,
            },
            optional: true,
        },
        soDate: String,
        size: {
            type: String,
            optional: true,
            validate: (s) => ["sm", "md", "lg", "xl", "fs", "fullscreen"].includes(s),
        },
        edit: { type: Boolean, optional: true },
        options: {
            type: Object,
            optional: true,
            shape: {
                canChangeVariant: { type: Boolean, optional: true },
                showQuantity: { type: Boolean, optional: true },
                showPrice: { type: Boolean, optional: true },
                showPackaging: { type: Boolean, optional: true },
            },
        },
        save: Function,
        discard: Function,
        close: Function, // This is the close from the env of the Dialog Component
    };
    static defaultProps = {
        edit: false,
    };

    setup() {
        this.title = _t("Configure your product");
        this.env.dialogData.dismiss = !this.props.edit && this.props.discard.bind(this);
        this.state = useState({
            products: [],
            optionalProducts: [],
        });
        // Nest the currency id in an object so that it stays up to date in the `env`, even if we
        // modify it in `onWillStart` afterwards.
        this.currency = { id: this.props.currencyId };
        // `update_combination` is fired by the quantity buttons, the UoM radios and every
        // PTAV change, all of which a user can trigger faster than the round trip. Without
        // sequencing the *last response* wins rather than the last request, and the dialog
        // ends up showing one quantity's price against another quantity — which the total
        // in the footer then multiplies. One per product: two products' prices are
        // independent and must not cancel each other.
        this._combinationRequests = new Map();
        this.getValuesUrl = "/sale/product_configurator/get_values";
        this.createProductUrl = "/sale/product_configurator/create_product";
        this.updateCombinationUrl = "/sale/product_configurator/update_combination";
        this.getOptionalProductsUrl =
            "/sale/product_configurator/get_optional_products";

        useSubEnv({
            mainProductTmplId: this.props.productTemplateId,
            currency: this.currency,
            canChangeVariant: this.props.options?.canChangeVariant ?? true,
            showQuantity: this.props.options?.showQuantity ?? true,
            showPackaging: this.props.options?.showPackaging ?? true,
            showPrice: this.props.options?.showPrice ?? true,
            addProduct: this._addProduct.bind(this),
            removeProduct: this._removeProduct.bind(this),
            setQuantity: this._setQuantity.bind(this),
            setUoM: this._setUnitOfMeasure.bind(this),
            updateProductTemplateSelectedPTAV:
                this._updateProductTemplateSelectedPTAV.bind(this),
            updatePTAVCustomValue: this._updatePTAVCustomValue.bind(this),
            isPossibleCombination,
        });

        onWillStart(async () => {
            const { products, optional_products, currency_id } = await this._loadData(
                this.props.edit,
            );

            // If the product configurator is opened after the combo configurator (which happens if
            // a combo product has optional products), `_loadData` will return a single product
            // (i.e. the combo product), which should be linked to the previously selected combo
            // items.
            const mainProduct = findProduct(products, this.env.mainProductTmplId);
            mainProduct.selectedComboItems = this.props.selectedComboItems || [];

            this.state.products = products;
            this.state.optionalProducts = optional_products;
            for (const customPtav of this.props.customPtavs) {
                this._updatePTAVCustomValue(
                    this.env.mainProductTmplId,
                    customPtav.id,
                    customPtav.value,
                );
            }
            checkExclusions(this._allProducts, mainProduct);
            // Use the currency id retrieved from the server if none was provided in the props.
            this.currency.id ??= currency_id;
        });
    }

    get totalMessage() {
        return _t("Total: %s", this.getFormattedTotal());
    }

    /**
     * Return the total of the product in the list, in the currency of the `sale.order`.
     *
     * @return {String} - The sum of all items in the list, in the currency of the `sale.order`.
     */
    getFormattedTotal() {
        const total = (this.state.products || []).reduce(
            (sum, product) => sum + product.price * product.quantity,
            0,
        );
        return formatCurrency(total, this.currency.id);
    }

    //--------------------------------------------------------------------------
    // Data Exchanges
    //--------------------------------------------------------------------------

    async _loadData(onlyMainProduct) {
        return rpc(this.getValuesUrl, {
            product_template_id: this.props.productTemplateId,
            quantity: this.props.quantity,
            currency_id: this.currency.id,
            so_date: this.props.soDate,
            product_uom_id: this.props.productUOMId,
            company_id: this.props.companyId,
            pricelist_id: this.props.pricelistId,
            ptav_ids: this.props.ptavIds,
            only_main_product: onlyMainProduct,
            show_packaging: this.env.showPackaging,
            ...this._getAdditionalRpcParams(),
        });
    }

    async _createProduct(product) {
        return rpc(this.createProductUrl, {
            product_template_id: product.product_tmpl_id,
            ptav_ids: getCombination(product),
        });
    }

    async _updateCombination(product, quantity, uomId) {
        return rpc(this.updateCombinationUrl, {
            product_template_id: product.product_tmpl_id,
            ptav_ids: getCombination(product),
            currency_id: this.currency.id,
            so_date: this.props.soDate,
            quantity: quantity,
            product_uom_id: uomId,
            company_id: this.props.companyId,
            pricelist_id: this.props.pricelistId,
            ...this._getAdditionalRpcParams(),
        });
    }

    /**
     * Run `_updateCombination` for a product such that only the newest call for that
     * product can settle. A superseded call never resolves, so callers must treat it as
     * "someone else is now in charge" rather than as a result.
     *
     * @param {Object} product
     * @param {Number} quantity
     * @param {Number} uomId
     * @return {Promise<Object>} Resolves only if this call is still the latest one.
     */
    _updateCombinationSequenced(product, quantity, uomId) {
        let keepLast = this._combinationRequests.get(product.product_tmpl_id);
        if (!keepLast) {
            keepLast = new KeepLast();
            this._combinationRequests.set(product.product_tmpl_id, keepLast);
        }
        return keepLast.add(this._updateCombination(product, quantity, uomId));
    }

    async _getOptionalProducts(product) {
        return rpc(this.getOptionalProductsUrl, {
            product_template_id: product.product_tmpl_id,
            ptav_ids: getCombination(product),
            parent_ptav_ids: getParentsCombination(this._allProducts, product),
            currency_id: this.currency.id,
            so_date: this.props.soDate,
            company_id: this.props.companyId,
            pricelist_id: this.props.pricelistId,
            ...this._getAdditionalRpcParams(),
        });
    }

    /**
     * Hook to append additional RPC params in overriding modules.
     *
     * @return {Object} - The additional RPC params.
     */
    _getAdditionalRpcParams() {
        return {};
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Add the product to the list of products and fetch his optional products.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     */
    async _addProduct(productTmplId) {
        const index = this.state.optionalProducts.findIndex(
            (p) => p.product_tmpl_id === productTmplId,
        );
        if (index >= 0) {
            this.state.products.push(...this.state.optionalProducts.splice(index, 1));
            // Fetch optional product from the server with the parent combination.
            const product = this._findProduct(productTmplId);
            // Filter out optional products that are already loaded in the configurator.
            const newOptionalProducts = (
                await this._getOptionalProducts(product)
            ).filter((p) => !this._findProduct(p.product_tmpl_id));
            this.state.optionalProducts.push(...newOptionalProducts);
        }
    }

    /**
     * Remove the product and his optional products from the list of products.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     */
    _removeProduct(productTmplId) {
        const index = this.state.products.findIndex(
            (p) => p.product_tmpl_id === productTmplId,
        );
        if (index >= 0) {
            this.state.optionalProducts.push(...this.state.products.splice(index, 1));
            for (const childProduct of getChildProducts(
                this._allProducts,
                productTmplId,
            )) {
                this._removeProduct(childProduct.product_tmpl_id);
                this.state.optionalProducts.splice(
                    this.state.optionalProducts.findIndex(
                        (p) => p.product_tmpl_id === childProduct.product_tmpl_id,
                    ),
                    1,
                );
            }
        }
    }

    /**
     * Set the quantity of the product to a given value.
     *
     * If the value is less than or equal to zero, the product is removed from the product list
     * instead, unless it is the main product, in which case the quantity is set to 1.
     *
     * Note: if a newer quantity change supersedes this one, the returned promise never
     * settles (see `_updateCombinationSequenced`). Callers must not depend on it to
     * decide anything the newer call will decide for them.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     * @param {Number} quantity - The new quantity of the product.
     * @return {Boolean} - Whether the quantity was updated.
     */
    async _setQuantity(productTmplId, quantity) {
        if (quantity <= 0) {
            if (productTmplId === this.env.mainProductTmplId) {
                quantity = 1;
            } else {
                this._removeProduct(productTmplId);
                return true;
            }
        }
        const product = this._findProduct(productTmplId);
        if (product.quantity === quantity) {
            return false;
        }
        product.quantity = quantity;
        this._applyCombination(
            product,
            await this._updateCombinationSequenced(product, quantity, product.uom.id),
        );

        return true;
    }

    /**
     * Set the uom of the product to a given value.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     * @param {Number} uomId - The new uom of the product, as an `uom.uom` id.
     *
     * @return {Boolean} - Whether the uom was updated.
     */
    async _setUnitOfMeasure(productTmplId, uomId) {
        const product = this._findProduct(productTmplId);
        if (product.uom.id === uomId) {
            return false;
        }
        const combination = await this._updateCombinationSequenced(
            product,
            product.quantity,
            uomId,
        );
        this._handleUnitOfMeasureUpdate(product, combination, uomId);

        return true;
    }

    /**
     * Apply the update after changing the product uom.
     *
     * @param {Object} product - The product for which the uom was changed.
     * @param {Object} combination - The result of the `_updateCombination`.
     * @param {Number} uomId - The new uom of the product, as an `uom.uom` id.
     */
    _handleUnitOfMeasureUpdate(product, combination, uomId) {
        this._applyCombination(product, combination);
        product.uom = product.available_uoms.find((uom) => uom.id === uomId);
    }

    /**
     * Apply an `update_combination` response to a product.
     *
     * Every caller applies the *whole* response rather than picking `price` out of it:
     * `show_extra_price` is derived server-side from the matched pricelist rule, and the
     * matched rule depends on the quantity, so cherry-picking left it (and
     * `display_name`) describing a combination the user had already moved away from.
     *
     * @param {Object} product - The product to update.
     * @param {Object} combination - The result of `_updateCombination`.
     */
    _applyCombination(product, combination) {
        Object.assign(product, combination, { price: parseFloat(combination.price) });
    }

    /**
     * Change the value of `selected_attribute_value_ids` on the given PTAL in the product.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     * @param {Number} ptalId - The PTAL id, as a `product.template.attribute.line` id.
     * @param {Number} ptavId - The PTAV id, as a `product.template.attribute.value` id.
     * @param {Boolean} isMulti - Whether multiple `product.template.attribute.value` can be selected.
     */
    async _updateProductTemplateSelectedPTAV(productTmplId, ptalId, ptavId, isMulti) {
        const product = this._findProduct(productTmplId);
        const ptal = product.attribute_lines.find((line) => line.id === ptalId);
        ptavId = parseInt(ptavId);
        if (isMulti) {
            const selectedPtavIds = new Set(ptal.selected_attribute_value_ids);
            selectedPtavIds.has(ptavId)
                ? selectedPtavIds.delete(ptavId)
                : selectedPtavIds.add(ptavId);
            ptal.selected_attribute_value_ids = Array.from(selectedPtavIds);
        } else {
            ptal.selected_attribute_value_ids = [ptavId];
        }
        checkExclusions(this._allProducts, product);
        if (isPossibleCombination(product)) {
            this._applyCombination(
                product,
                await this._updateCombinationSequenced(
                    product,
                    product.quantity,
                    product.uom.id,
                ),
            );
            // When a combination should exist but was deleted from the database, it should not be
            // selectable and considered as an exclusion.
            //
            // "Should exist" means every *variant-creating* line is `always`; a
            // `no_variant` line has no bearing on whether a variant exists, so it must
            // not veto this branch. And what gets recorded has to be the variant
            // combination, since that is what `archived_combinations` is compared
            // against (see `getVariantCombination`).
            if (
                !product.id &&
                product.attribute_lines.every(
                    (ptal) => ptal.create_variant !== "dynamic",
                )
            ) {
                product.archived_combinations = product.archived_combinations.concat([
                    getVariantCombination(product),
                ]);
                checkExclusions(this._allProducts, product);
            }
        }
    }

    /**
     * Set the custom value for a given custom PTAV.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     * @param {Number} ptavId - The PTAV id, as a `product.template.attribute.value` id.
     * @param {String} customValue - The custom value.
     */
    _updatePTAVCustomValue(productTmplId, ptavId, customValue) {
        const product = this._findProduct(productTmplId);
        product.attribute_lines.find((ptal) =>
            ptal.selected_attribute_value_ids.includes(ptavId),
        ).customValue = customValue;
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * The pool of products (main + optional) that combination/exclusion lookups
     * resolve parents and children against.
     *
     * @return {Object[]}
     */
    get _allProducts() {
        return [...this.state.products, ...this.state.optionalProducts];
    }

    /**
     * Return the product given his template id.
     *
     * @param {Number} productTmplId - The product template id, as a `product.template` id.
     * @return {Object} - The product.
     */
    _findProduct(productTmplId) {
        // The product might be in either of the two lists `products` or `optional_products`.
        return findProduct(this._allProducts, productTmplId);
    }

    /**
     * Check if all the products selected have a valid combination.
     *
     * @return {Boolean} - Whether all the products selected have a valid combination or not.
     */
    isPossibleConfiguration() {
        return this.state.products.every(isPossibleCombination);
    }

    /**
     * Confirm the current combination(s).
     *
     * @return {undefined}
     */
    async onConfirm(options) {
        if (!this.isPossibleConfiguration()) {
            return;
        }
        // Create the products with dynamic attributes. These calls are independent of
        // each other, so a configuration with several dynamic products does not need to
        // pay for them one round trip at a time.
        await Promise.all(
            this.state.products
                .filter(
                    (product) =>
                        !product.id &&
                        product.attribute_lines.some(
                            (ptal) => ptal.create_variant === "dynamic",
                        ),
                )
                .map(async (product) => {
                    product.id = parseInt(await this._createProduct(product));
                }),
        );
        await this.props.save(
            findProduct(this.state.products, this.env.mainProductTmplId),
            this.state.products.filter(
                (p) => p.product_tmpl_id !== this.env.mainProductTmplId,
            ),
            options,
        );
        this.props.close();
    }

    /**
     * Discard the modal.
     */
    onDiscard() {
        if (!this.props.edit) {
            this.props.discard(); // clear the line
        }
        this.props.close();
    }
}
