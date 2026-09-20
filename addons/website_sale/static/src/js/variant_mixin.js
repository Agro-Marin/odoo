/** @odoo-module native */
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/translation";
import { rpc } from "@web/core/network";
import { KeepLast } from "@web/core/utils/concurrency";
import { memoize } from "@web/core/utils/functions";
import { insertThousandsSep } from "@web/core/utils/format/numbers";
import { throttleForAnimation } from "@web/core/utils/timing";
import { markup } from "@odoo/owl";
import wSaleUtils from "@website_sale/js/website_sale_utils";

const VariantMixin = {
    /**
     * @private
     * @param {Event} ev
     * @returns {Deferred}
     */
    async _getCombinationInfo(ev) {
        if (ev.target.classList.contains("variant_custom_value"))
            return Promise.resolve();
        const parent = ev.target.closest(".js_product");
        if (!parent) return Promise.resolve();
        const combination = wSaleUtils.getSelectedAttributeValues(parent);

        const combinationInfo = await this.waitFor(
            rpc("/website_sale/get_combination_info", {
                product_template_id: parseInt(
                    parent.querySelector(".product_template_id")?.value,
                ),
                product_id: this._getProductId(parent),
                combination: combination,
                add_qty: parseInt(parent.querySelector('input[name="add_qty"]')?.value),
                uom_id: this._getUoMId(parent),
                context: this.context,
                ...this._getOptionalCombinationInfoParam(parent),
            }),
        );
        this._onChangeCombination(ev, parent, combinationInfo);
        this._checkExclusions(parent, combination);
    },

    _getUoMId(element) {
        return parseInt(element.querySelector('input[name="uom_id"]:checked')?.value);
    },

    /**
     * @param {Element} product
     */
    _getOptionalCombinationInfoParam() {
        return {};
    },

    /**
     * @param {Element} el
     */
    handleCustomValues(el) {
        let variantContainer;
        let customInput = false;
        if (el.matches("input[type=radio]:checked")) {
            variantContainer = el.closest("ul").closest("li");
            customInput = el;
        } else if (el.matches("select")) {
            variantContainer = el.closest("li");
            customInput = el.querySelector(`option[value="${el.value}"]`);
        }

        if (variantContainer) {
            const customValue = variantContainer.querySelector(".variant_custom_value");
            if (customInput && customInput.dataset.isCustom === "True") {
                const attributeValueId = customInput.dataset.valueId;
                if (
                    !customValue ||
                    customValue.dataset.customProductTemplateAttributeValueId !==
                        attributeValueId
                ) {
                    customValue?.remove();

                    const previousCustomValue = customInput.getAttribute(
                        "previous_custom_value",
                    );
                    const input = document.createElement("input");
                    input.type = "text";
                    input.dataset.customProductTemplateAttributeValueId =
                        attributeValueId;
                    input.classList.add(
                        "variant_custom_value",
                        "custom_value_radio",
                        "form-control",
                        "mt-2",
                    );
                    input.setAttribute("placeholder", customInput.dataset.valueName);
                    variantContainer.appendChild(input);
                    if (previousCustomValue) {
                        input.value = previousCustomValue;
                    }
                }
            } else {
                customValue?.remove();
            }
        }
    },

    /**
     * @param {Element} container
     */
    triggerVariantChange(container) {
        container
            .querySelectorAll("ul[data-attribute-exclusions]")
            .forEach((el) => el.dispatchEvent(new Event("change")));
        container
            .querySelectorAll(
                "input.js_variant_change:checked, select.js_variant_change",
            )
            .forEach((el) => this.handleCustomValues(el));
    },

    /**
     * @private
     * @param {Element} parent
     * @param {Array} combination
     */
    _checkExclusions(parent, combination) {
        const combinationDataJson = parent.querySelector(
            "ul[data-attribute-exclusions]",
        ).dataset.attributeExclusions;
        const combinationData = combinationDataJson
            ? JSON.parse(combinationDataJson)
            : {};

        parent
            .querySelectorAll("option, input, label, .o_variant_pills")
            .forEach((el) => {
                el.classList.remove("css_not_available");
            });
        parent.querySelectorAll("option, input").forEach((el) => {
            const li = el.closest("li");
            if (li) {
                li.removeAttribute("title");
                li.dataset.excludedBy = "";
            }
        });
        if (combinationData.exclusions) {
            Object.values(combination).forEach((current_ptav) => {
                if (Object.hasOwn(combinationData.exclusions, current_ptav)) {
                    Object.values(combinationData.exclusions[current_ptav]).forEach(
                        (excluded_ptav) => {
                            this._disableInput(
                                parent,
                                excluded_ptav,
                                current_ptav,
                                combinationData.mapped_attribute_names,
                            );
                        },
                    );
                }
            });
        }
        if (combinationData.archived_combinations) {
            const variantCombination =
                wSaleUtils.getSelectedVariantAttributeValues(parent);
            combinationData.archived_combinations.forEach((excludedCombination) => {
                const ptavCommon = excludedCombination.filter((ptav) =>
                    variantCombination.includes(ptav),
                );
                if (
                    variantCombination.length === excludedCombination.length &&
                    ptavCommon.length === variantCombination.length
                ) {
                    variantCombination.forEach((ptav) => {
                        variantCombination.forEach((ptavOther) => {
                            if (ptav === ptavOther) {
                                return;
                            }
                            this._disableInput(
                                parent,
                                ptav,
                                ptavOther,
                                combinationData.mapped_attribute_names,
                            );
                        });
                    });
                } else if (
                    variantCombination.length === excludedCombination.length &&
                    ptavCommon.length === variantCombination.length - 1
                ) {
                    const unavailablePtav = excludedCombination.find(
                        (ptav) => !variantCombination.includes(ptav),
                    );
                    excludedCombination.forEach((ptav) => {
                        if (ptav === unavailablePtav) {
                            return;
                        }
                        this._disableInput(
                            parent,
                            unavailablePtav,
                            ptav,
                            combinationData.mapped_attribute_names,
                        );
                    });
                }
            });
        }
    },

    /**
     * @param {Element} parent
     */
    _getProductId(parent) {
        return parseInt(parent.querySelector(".product_id").value);
    },

    /**
     * @private
     * @param {Element} parent
     * @param {integer} attributeValueId
     * @param {integer} excludedBy
     * @param {Object} attributeNames
     * @param {string} [productName]
     */
    _disableInput(parent, attributeValueId, excludedBy, attributeNames, productName) {
        const input = parent.querySelector(
            `option[value="${attributeValueId}"], input[value="${attributeValueId}"]`,
        );
        input.classList.add("css_not_available");
        input.closest("label")?.classList?.add("css_not_available");
        input.closest(".o_variant_pills")?.classList?.add("css_not_available");

        const li = input.closest("li");

        if (li && excludedBy && attributeNames) {
            const excludedByData = li.dataset.excludedBy
                ? li.dataset.excludedBy.split(",")
                : [];

            let excludedByName = attributeNames[excludedBy];
            if (productName) {
                excludedByName = `${productName} (${excludedByName})`;
            }
            excludedByData.push(excludedByName);

            li.setAttribute(
                "title",
                _t("Not available with %s", excludedByData.join(", ")),
            );
            li.dataset.excludedBy = excludedByData.join(",");
        }
    },

    /**
     * @private
     * @param {MouseEvent} ev
     * @param {Element} parent
     * @param {Array} combination
     */
    _onChangeCombination(ev, parent, combination) {
        const isCombinationPossible = !!combination.is_combination_possible;
        const precision = combination.currency_precision;
        const productPrice = parent.querySelector(".product_price");
        if (productPrice && !productPrice.classList.contains("decimal_precision")) {
            productPrice.classList.add("decimal_precision");
            productPrice.dataset.precision = precision;
        }
        const pricePerUom = parent
            .querySelector(".o_base_unit_price")
            ?.querySelector(".oe_currency_value");
        if (pricePerUom) {
            const hasPrice = isCombinationPossible && combination.base_unit_price !== 0;
            pricePerUom
                .closest(".o_base_unit_price_wrapper")
                .classList.toggle("d-none", !hasPrice);
            if (hasPrice) {
                pricePerUom.textContent = this._priceToStr(
                    combination.base_unit_price,
                    precision,
                );
                const unit = parent.querySelector(".oe_custom_base_unit");
                if (unit) {
                    unit.textContent = combination.base_unit_name;
                }
            }
        }

        if ("product_tracking_info" in combination) {
            const product = document.querySelector("#product_detail");
            product.dispatchEvent(
                new CustomEvent("view_item_event", {
                    detail: combination["product_tracking_info"],
                }),
            );
        }
        const addToCart = parent.querySelector("#add_to_cart_wrap");
        const contactUsButton = parent
            .closest("#product_details")
            ?.querySelector("#contact_us_wrapper");
        const quantity = parent.querySelector(".css_quantity");
        const productUnavailable = parent.querySelector("#product_unavailable");

        const preventSale = combination.prevent_zero_price_sale;
        productPrice?.classList?.toggle("d-inline-block", !preventSale);
        productPrice?.classList?.toggle("d-none", preventSale);
        quantity?.classList?.toggle("d-inline-flex", !preventSale);
        quantity?.classList?.toggle("d-none", preventSale);
        addToCart?.classList?.toggle("d-inline-flex", !preventSale);
        addToCart?.classList?.toggle("d-none", preventSale);
        contactUsButton?.classList?.toggle("d-none", !preventSale);
        contactUsButton?.classList?.toggle("d-flex", preventSale);
        productUnavailable?.classList?.toggle("d-none", !preventSale);
        productUnavailable?.classList?.toggle("d-flex", preventSale);

        if (contactUsButton) {
            const contactUsButtonLink = contactUsButton.querySelector("a");
            const url = contactUsButtonLink.getAttribute("data-url");
            contactUsButtonLink.setAttribute(
                "href",
                `${url}?subject=${combination.display_name}`,
            );
        }

        const price = parent
            .querySelector(".oe_price")
            ?.querySelector(".oe_currency_value");
        const defaultPrice = parent
            .querySelector(".oe_default_price")
            ?.querySelector(".oe_currency_value");
        const comparePrice = parent.querySelector(".oe_compare_list_price");
        if (price) {
            price.textContent = this._priceToStr(combination.price, precision);
        }
        if (defaultPrice) {
            defaultPrice.textContent = this._priceToStr(
                combination.list_price,
                precision,
            );
            defaultPrice
                .closest(".oe_website_sale")
                .classList.toggle("discount", combination.has_discounted_price);
            defaultPrice.parentElement.classList.toggle(
                "d-none",
                !combination.has_discounted_price,
            );
        }
        if (comparePrice) {
            comparePrice.classList.toggle("d-none", combination.has_discounted_price);
        }

        this._toggleDisable(parent, isCombinationPossible);

        if (!combination.no_product_change) {
            this._updateProductImage(
                parent.closest("tr.js_product, .oe_website_sale"),
                combination.carousel,
            );
            const productTags = parent.querySelector(".o_product_tags");
            productTags?.insertAdjacentHTML(
                "beforebegin",
                markup(combination.product_tags),
            );
            productTags?.remove();
        }

        const productIdInput = parent.querySelector(".product_id");
        productIdInput.value = combination.product_id || 0;
        productIdInput.dispatchEvent(new Event("change", { bubbles: true }));

        this.handleCustomValues(ev.target);
    },

    /**
     * @private
     * @param {float} price
     * @param {integer} precision
     * @returns {string}
     */
    _priceToStr: function (price, precision) {
        if (!Number.isInteger(precision)) {
            precision = parseInt(
                this.el.querySelector(".decimal_precision:last-of-type")?.dataset
                    .precision ?? 2,
            );
        }
        const formatted = price.toFixed(precision).split(".");
        const { thousandsSep, decimalPoint, grouping } = localization;
        formatted[0] = insertThousandsSep(formatted[0], thousandsSep, grouping);
        return formatted.join(decimalPoint);
    },

    /**
     * @private
     * @param {string} uniqueId
     * @returns {function}
     */
    _throttledGetCombinationInfo: memoize(function (self) {
        const keepLast = new KeepLast();
        const _getCombinationInfo = throttleForAnimation(
            self._getCombinationInfo.bind(self),
        );
        return (ev, params) => keepLast.add(_getCombinationInfo(ev, params));
    }),
};

export default VariantMixin;
