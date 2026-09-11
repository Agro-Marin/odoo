/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { ComboConfiguratorDialog } from "@sale/js/combo_configurator_dialog/combo_configurator_dialog";
import { ProductCombo } from "@sale/js/models/product_combo";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { getSelectedCustomPtav, serializeComboItem } from "@sale/js/sale_utils";
import { browser } from "@web/core/browser/browser";
import { serializeDateTime } from "@web/core/l10n/dates";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { redirect } from "@web/core/utils/urls";
import { session } from "@web/session";

const { DateTime } = luxon;

/**
 * @typedef {Object} CustomAttributeValues
 * @property {Number} custom_product_template_attribute_value_id
 * @property {String} custom_value
 */

export class CartService {
    static dependencies = ["cartNotificationService", "dialog"];

    /**
     * @returns {Object}
     */
    constructor() {
        return this.setup(...arguments);
    }

    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {import("services").ServiceFactories} services
     * @returns {Object}
     */
    setup(_env, services) {
        this.cartNotificationService = services.cartNotificationService;
        this.dialog = services.dialog;
        this.rpc = rpc;

        return {
            add: (...args) => this.add(...args),
        };
    }

    /**
     * @param {Object} product
     * @param {Number} product.productTemplateId
     * @param {Number} [product.productId=undefined]
     * @param {Number} [product.quantity=1]
     * @param {Number} [product.uom_id=undefined]
     * @param {Number[]} [product.ptavs=[]]
     * @param {CustomAttributeValues[]} [product.productCustomAttributeValues=[]]
     * @param {Number[]} [product.noVariantAttributeValues=[]]
     * @param {Boolean} [product.isCombo=false]
     * @param {*} [product.rest]
     * @param {Object} [options]
     * @param {Boolean} [options.isBuyNow=false]
     * @param {Boolean} [options.redirectToCart=true]
     * @param {Boolean} [options.isConfigured=false]
     * @param {Boolean} [options.showQuantity=true]
     * @returns {Number}
     */
    async add(
        {
            productTemplateId,
            productId = undefined,
            quantity = 1,
            uomId = undefined,
            ptavs = [],
            productCustomAttributeValues = [],
            noVariantAttributeValues = [],
            isCombo = false,
            ...rest
        },
        {
            isBuyNow = false,
            redirectToCart = true,
            isConfigured = false,
            showQuantity = true,
        } = {},
    ) {
        if (!productId && ptavs.length) {
            productId = await this.rpc("/sale/create_product_variant", {
                product_template_id: productTemplateId,
                product_template_attribute_value_ids: ptavs.concat(
                    noVariantAttributeValues,
                ),
            });
        }

        if (isCombo) {
            const { combos, ...remainingData } = await this.rpc(
                "/website_sale/combo_configurator/get_data",
                {
                    product_tmpl_id: productTemplateId,
                    quantity: quantity,
                    date: serializeDateTime(DateTime.now()),
                    ...rest,
                },
            );
            const preselectedComboItems = combos
                .map((combo) => new ProductCombo(combo))
                .map((combo) => combo.preselectedComboItem)
                .filter(Boolean);
            if (preselectedComboItems.length === combos.length) {
                return this._makeRequest({
                    productTemplateId: productTemplateId,
                    productId: productId,
                    quantity: remainingData.quantity,
                    uomId: uomId,
                    linked_products: preselectedComboItems.map((comboItem) =>
                        this._serializeComboItem(
                            comboItem,
                            productTemplateId,
                            remainingData.quantity,
                        ),
                    ),
                    shouldRedirectToCart: isBuyNow && redirectToCart,
                    ...rest,
                });
            }
            return this._openComboConfigurator(
                productTemplateId,
                productId,
                combos.map((combo) => new ProductCombo(combo)),
                remainingData,
                {
                    isBuyNow: isBuyNow,
                    showQuantity: showQuantity,
                },
                rest,
            );
        }

        if (isBuyNow) {
            return this._makeRequest({
                productTemplateId,
                productId,
                quantity,
                uomId,
                productCustomAttributeValues,
                noVariantAttributeValues,
                shouldRedirectToCart: isBuyNow && redirectToCart,
                ...rest,
            });
        }

        const shouldShowProductConfigurator = await this.rpc(
            "/website_sale/should_show_product_configurator",
            {
                product_template_id: productTemplateId,
                ptav_ids: ptavs,
                is_product_configured: isConfigured,
            },
        );
        if (shouldShowProductConfigurator) {
            return this._openProductConfigurator(
                productTemplateId,
                quantity,
                uomId,
                ptavs.concat(noVariantAttributeValues),
                productCustomAttributeValues,
                {
                    isBuyNow: isBuyNow,
                    isMainProductConfigurable: !isConfigured,
                    showQuantity: showQuantity,
                },
                rest,
            );
        }

        return this._makeRequest({
            productTemplateId,
            productId,
            quantity,
            uomId,
            productCustomAttributeValues,
            noVariantAttributeValues,
            shouldRedirectToCart: isBuyNow && redirectToCart,
            ...rest,
        });
    }

    /**
     * @private
     * @param {Number} productTemplateId
     * @param {Number} productId
     * @param {ProductCombo[]} combos
     * @param {Object} remainingData
     * @param {Number} remainingData.currency_id
     * @param {String} remainingData.display_name
     * @param {Number} remainingData.price
     * @param {Number} remainingData.product_tmpl_id
     * @param {Number} remainingData.quantity
     * @param {Object} [options]
     * @param {Boolean} [options.isBuyNow]
     * @param {Boolean} [options.showQuantity]
     * @param {Object} [additionalData]
     * @returns {Number}
     */
    async _openComboConfigurator(
        productTemplateId,
        productId,
        combos,
        remainingData,
        options,
        additionalData,
    ) {
        return await new Promise((resolve) => {
            this.dialog.add(ComboConfiguratorDialog, {
                combos: combos,
                ...remainingData,
                date: serializeDateTime(DateTime.now()),
                edit: false,
                isFrontend: true,
                options,
                ...additionalData,
                save: async (comboProductData, selectedComboItems, options) => {
                    resolve(
                        this._makeRequest({
                            productTemplateId: productTemplateId,
                            productId: productId,
                            quantity: comboProductData.quantity,
                            linked_products: selectedComboItems.map((comboItem) =>
                                this._serializeComboItem(
                                    comboItem,
                                    productTemplateId,
                                    comboProductData.quantity,
                                ),
                            ),
                            shouldRedirectToCart: options.goToCart,
                            ...additionalData,
                        }),
                    );
                },
                discard: () => resolve(0),
            });
        });
    }

    /**
     * @private
     * @param {Number} productTemplateId
     * @param {Number} quantity
     * @param {Number} [uomId]
     * @param {Number[]} combination
     * @param {CustomAttributeValues[]} productCustomAttributeValues
     * @param {Object} [options]
     * @param {Boolean} [options.isBuyNow]
     * @param {Boolean} [options.isMainProductConfigurable]
     * @param {Boolean} [options.showQuantity]
     * @param {Object} [additionalData]
     * @returns {Number}
     */
    async _openProductConfigurator(
        productTemplateId,
        quantity,
        uomId,
        combination,
        productCustomAttributeValues,
        options,
        additionalData,
    ) {
        return await new Promise((resolve) => {
            this.dialog.add(ProductConfiguratorDialog, {
                productTemplateId: productTemplateId,
                ptavIds: combination,
                customPtavs: productCustomAttributeValues.map((customPtav) => ({
                    id: customPtav.custom_product_template_attribute_value_id,
                    value: customPtav.custom_value,
                })),
                quantity: quantity,
                productUOMId: uomId,
                soDate: serializeDateTime(DateTime.now()),
                edit: false,
                isFrontend: true,
                selectedComboItems: [],
                options,
                ...additionalData,
                save: async (mainProduct, optionalProducts, options) => {
                    const product = this._serializeProduct(mainProduct);
                    resolve(
                        this._makeRequest({
                            productTemplateId: product.product_template_id,
                            productId: product.product_id,
                            quantity: product.quantity,
                            uom_id: product.uom_id,
                            productCustomAttributeValues:
                                product.product_custom_attribute_values,
                            noVariantAttributeValues:
                                product.no_variant_attribute_value_ids,
                            linked_products: optionalProducts.map(
                                this._serializeProduct,
                            ),
                            shouldRedirectToCart: options.goToCart,
                            ...additionalData,
                        }),
                    );
                },
                discard: () => resolve(0),
            });
        });
    }

    /**
     * @private
     * @param {Object} product
     * @returns {Object}
     */
    _serializeProduct(product) {
        let serializedProduct = {
            product_id: product.id,
            product_template_id: product.product_tmpl_id,
            parent_product_template_id: product.parent_product_tmpl_id,
            quantity: product.quantity,
            uom_id: product.uom.id,
        };

        if (!product.attribute_lines) {
            return serializedProduct;
        }

        serializedProduct.product_custom_attribute_values = [];
        for (const ptal of product.attribute_lines) {
            const selectedCustomPtav = getSelectedCustomPtav(ptal);
            if (selectedCustomPtav) {
                serializedProduct.product_custom_attribute_values.push({
                    custom_product_template_attribute_value_id: selectedCustomPtav.id,
                    custom_value: ptal.customValue ?? "",
                });
            }
        }

        serializedProduct.no_variant_attribute_value_ids = product.attribute_lines
            .filter((ptal) => ptal.create_variant === "no_variant")
            .flatMap((ptal) => ptal.selected_attribute_value_ids);

        return serializedProduct;
    }

    /**
     * @private
     * @param {ProductComboItem} comboItem
     * @param {Number} parentProductTemplateId
     * @param {Number} quantity
     * @returns {Object}
     */
    _serializeComboItem(comboItem, parentProductTemplateId, quantity) {
        return {
            product_template_id: comboItem.product.product_tmpl_id,
            parent_product_template_id: parentProductTemplateId,
            quantity: quantity,
            ...serializeComboItem(comboItem),
        };
    }

    /**
     * @private
     * @param {Object} data
     * @param {Number} data.productTemplateId
     * @param {Number} data.productId
     * @param {Number} data.uomId
     * @param {Number} data.quantity
     * @param {CustomAttributeValues[]} [data.productCustomAttributeValues=[]]
     * @param {Number[]} [data.noVariantAttributeValues=[]]
     * @param {Boolean} [data.shouldRedirectToCart=false]
     * @param {*} [data.rest]
     * @returns {Number}
     */
    async _makeRequest({
        productTemplateId,
        productId,
        quantity,
        uomId = undefined,
        productCustomAttributeValues = [],
        noVariantAttributeValues = [],
        shouldRedirectToCart = false,
        ...rest
    }) {
        const data = await this.rpc("/shop/cart/add", {
            product_template_id: productTemplateId,
            product_id: productId,
            quantity: quantity,
            uom_id: uomId,
            product_custom_attribute_values: productCustomAttributeValues,
            no_variant_attribute_value_ids: noVariantAttributeValues,
            ...rest,
        });
        if (shouldRedirectToCart || session.add_to_cart_action === "go_to_cart") {
            redirect("/shop/cart");
            return data.quantity;
        }
        if (
            data.cart_quantity &&
            data.cart_quantity !==
                browser.sessionStorage.getItem("website_sale_cart_quantity")
        ) {
            this._updateCartIcon(data.cart_quantity);
        }
        this._showCartNotification(data.notification_info);
        if (data.quantity) {
            this._trackProducts(data.tracking_info);
        }
        return data.quantity;
    }

    /**
     * @private
     * @param {Number} cartQuantity
     * @returns {void}
     */
    _updateCartIcon(cartQuantity) {
        browser.sessionStorage.setItem("website_sale_cart_quantity", cartQuantity);
        const cartQuantityElements = document.querySelectorAll(".my_cart_quantity");
        for (const cartQuantityElement of cartQuantityElements) {
            if (cartQuantity === 0) {
                cartQuantityElement.classList.add("d-none");
            } else {
                const cartIconElement = document.querySelector("li.o_wsale_my_cart");
                cartIconElement.classList.remove("d-none");
                cartQuantityElement.classList.remove("d-none");
                cartQuantityElement.classList.add("o_mycart_zoom_animation");
                setTimeout(() => {
                    cartQuantityElement.textContent = cartQuantity;
                    cartQuantityElement.classList.remove("o_mycart_zoom_animation");
                }, 300);
            }
        }
    }

    /**
     * @private
     * @param {Object} props
     * @param {Object} options
     * @returns {void}
     */
    _showCartNotification(props, options = {}) {
        if (props.lines) {
            this.cartNotificationService.add("", {
                lines: props.lines,
                currency_id: props.currency_id,
                ...options,
            });
        }
        if (props.warning) {
            this.cartNotificationService.add("", {
                warning: props.warning,
                ...options,
            });
        }
    }

    /**
     * @private
     * @param {Object[]} trackingInfo
     * @returns {void}
     */
    _trackProducts(trackingInfo) {
        document
            .querySelector(".oe_website_sale")
            .dispatchEvent(
                new CustomEvent("add_to_cart_event", { detail: trackingInfo }),
            );
    }
}

export const cartService = {
    dependencies: CartService.dependencies,
    async: ["add"],
    start(env, dependencies) {
        return new CartService(env, dependencies);
    },
};

registry.category("services").add("cart", cartService);
