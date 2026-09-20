/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";

const COMPARISON_PRODUCT_IDS_COOKIE_NAME = "comparison_product_ids";
const MAX_COMPARISON_PRODUCTS = 4;
const COMPARISON_EVENT = "comparison_products_changed";

/**
 * @return {Array<number>}
 */
function getComparisonProductIds() {
    return JSON.parse(cookie.get(COMPARISON_PRODUCT_IDS_COOKIE_NAME) || "[]");
}

/**
 * @param {ArrayLike<number>} productIds
 * @param {EventBus} bus
 */
function setComparisonProductIds(productIds, bus) {
    cookie.set(
        COMPARISON_PRODUCT_IDS_COOKIE_NAME,
        JSON.stringify(Array.from(productIds)),
    );
    notifyComparisonListeners(bus);
}

/**
 * @param {number} productId
 * @param {EventBus} bus
 */
function addComparisonProduct(productId, bus) {
    const productIds = new Set(getComparisonProductIds());
    productIds.add(productId);
    setComparisonProductIds(productIds, bus);
}

/**
 * @param {number} productId
 * @param {EventBus} bus
 */
function removeComparisonProduct(productId, bus) {
    const productIds = new Set(getComparisonProductIds());
    productIds.delete(productId);
    setComparisonProductIds(productIds, bus);
}

/**
 * @param {EventBus} bus
 */
function clearComparisonProducts(bus) {
    const productIds = getComparisonProductIds();
    cookie.delete(COMPARISON_PRODUCT_IDS_COOKIE_NAME);
    notifyComparisonListeners(bus);
    enableDisabledProducts(productIds);
}

/**
 * @param {EventBus} bus
 */
function notifyComparisonListeners(bus) {
    if (bus) {
        bus.dispatchEvent(new CustomEvent(COMPARISON_EVENT, { bubbles: true }));
    }
}

/**
 * @param {Element} el
 * @param {boolean} isDisabled
 */
function updateDisabled(el, isDisabled) {
    el.disabled = isDisabled;
    el.classList.toggle("disabled", isDisabled);
}

function enableDisabledProducts(productIds) {
    for (const productId of productIds) {
        const productCompareButton = document.querySelector(
            `.o_add_compare[data-product-product-id="${productId}"]`,
        );
        if (productCompareButton) {
            updateDisabled(productCompareButton, false);
        }
    }
}

export default {
    MAX_COMPARISON_PRODUCTS: MAX_COMPARISON_PRODUCTS,
    COMPARISON_EVENT: COMPARISON_EVENT,
    getComparisonProductIds: getComparisonProductIds,
    setComparisonProductIds: setComparisonProductIds,
    addComparisonProduct: addComparisonProduct,
    removeComparisonProduct: removeComparisonProduct,
    clearComparisonProducts: clearComparisonProducts,
    notifyComparisonListeners: notifyComparisonListeners,
    updateDisabled: updateDisabled,
    enableDisabledProducts: enableDisabledProducts,
};
