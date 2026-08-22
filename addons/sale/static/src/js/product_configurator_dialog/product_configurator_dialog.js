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
        close: Function,
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
        this.currency = { id: this.props.currencyId };
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
            this.currency.id ??= currency_id;
        });
    }

    get totalMessage() {
        return _t("Total: %s", this.getFormattedTotal());
    }

    /**
     * @return {String}
     */
    getFormattedTotal() {
        const total = (this.state.products || []).reduce(
            (sum, product) => sum + product.price * product.quantity,
            0,
        );
        return formatCurrency(total, this.currency.id);
    }

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
     * @param {Object} product
     * @param {Number} quantity
     * @param {Number} uomId
     * @return {Promise<Object>}
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
     * @return {Object}
     */
    _getAdditionalRpcParams() {
        return {};
    }

    /**
     * @param {Number} productTmplId
     */
    async _addProduct(productTmplId) {
        const index = this.state.optionalProducts.findIndex(
            (p) => p.product_tmpl_id === productTmplId,
        );
        if (index >= 0) {
            this.state.products.push(...this.state.optionalProducts.splice(index, 1));
            const product = this._findProduct(productTmplId);
            const newOptionalProducts = (
                await this._getOptionalProducts(product)
            ).filter((p) => !this._findProduct(p.product_tmpl_id));
            this.state.optionalProducts.push(...newOptionalProducts);
        }
    }

    /**
     * @param {Number} productTmplId
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
     * @param {Number} productTmplId
     * @param {Number} quantity
     * @return {Boolean}
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
     * @param {Number} productTmplId
     * @param {Number} uomId
     * @return {Boolean}
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
     * @param {Object} product
     * @param {Object} combination
     * @param {Number} uomId
     */
    _handleUnitOfMeasureUpdate(product, combination, uomId) {
        this._applyCombination(product, combination);
        product.uom = product.available_uoms.find((uom) => uom.id === uomId);
    }

    /**
     * @param {Object} product
     * @param {Object} combination
     */
    _applyCombination(product, combination) {
        Object.assign(product, combination, { price: parseFloat(combination.price) });
    }

    /**
     * @param {Number} productTmplId
     * @param {Number} ptalId
     * @param {Number} ptavId
     * @param {Boolean} isMulti
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
     * @param {Number} productTmplId
     * @param {Number} ptavId
     * @param {String} customValue
     */
    _updatePTAVCustomValue(productTmplId, ptavId, customValue) {
        const product = this._findProduct(productTmplId);
        product.attribute_lines.find((ptal) =>
            ptal.selected_attribute_value_ids.includes(ptavId),
        ).customValue = customValue;
    }

    /**
     * @return {Object[]}
     */
    get _allProducts() {
        return [...this.state.products, ...this.state.optionalProducts];
    }

    /**
     * @param {Number} productTmplId
     * @return {Object}
     */
    _findProduct(productTmplId) {
        return findProduct(this._allProducts, productTmplId);
    }

    /**
     * @return {Boolean}
     */
    isPossibleConfiguration() {
        return this.state.products.every(isPossibleCombination);
    }

    /**
     * @return {undefined}
     */
    async onConfirm(options) {
        if (!this.isPossibleConfiguration()) {
            return;
        }
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

    onDiscard() {
        if (!this.props.edit) {
            this.props.discard();
        }
        this.props.close();
    }
}
