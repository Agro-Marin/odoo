/** @odoo-module native */
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
import { patchDynamicContent } from "@web/public/utils";
import { rpc } from "@web/core/network";
import { Checkout } from "@website_sale/interactions/checkout";

patch(Checkout.prototype, {
    setup() {
        super.setup();
        patchDynamicContent(this.dynamicContent, {
            ".js_wsc_update_product_qty": {
                "t-on-click": this.onClickUpdateProductQty.bind(this),
            },
        });
        this.deliveryAddressTitle = this.el.querySelector(
            '[name="delivery_address_title"]',
        );
        if (this.deliveryAddressTitle) {
            this.deliveryTitle = this.deliveryAddressTitle.textContent;
            this.useDeliveryAsBillingLabel = this.el.querySelector(
                '[name="use_delivery_as_billing_text"]',
            );
            this.useDeliveryAsBillingLabelText =
                this.useDeliveryAsBillingLabel.textContent;
            this.inStoreTitle = _t("Contact Details");
            this.useDeliveryAsBillingLabelInStoreText = _t("Same as contact details");
            this._adaptDeliveryTitles();
        }
    },

    async selectDeliveryMethod() {
        this._adaptDeliveryTitles();
        await super.selectDeliveryMethod(...arguments);
    },

    /**
     * @param {Event} ev
     */
    async onClickUpdateProductQty(ev) {
        await this.waitFor(
            rpc("/shop/cart/update", {
                line_id: parseInt(ev.currentTarget.dataset.lineId, 10),
                product_id: parseInt(ev.currentTarget.dataset.productId, 10),
                quantity: parseInt(ev.currentTarget.dataset.availableQty || 0, 10),
            }),
        );
        window.location.reload();
    },

    /**
     * @private
     * @return {void}
     */
    _adaptDeliveryTitles() {
        const checkedRadio = document.querySelector(
            'input[name="o_delivery_radio"]:checked',
        );
        if (
            !checkedRadio ||
            !this.deliveryAddressTitle ||
            !this.useDeliveryAsBillingLabel
        ) {
            return;
        }
        if (checkedRadio.dataset.deliveryType === "in_store") {
            this.deliveryAddressTitle.textContent = this.inStoreTitle;
            this.useDeliveryAsBillingLabel.textContent =
                this.useDeliveryAsBillingLabelInStoreText;
        } else {
            this.deliveryAddressTitle.textContent = this.deliveryTitle;
            this.useDeliveryAsBillingLabel.textContent =
                this.useDeliveryAsBillingLabelText;
        }
    },

    /**
     * @override
     */
    _updatePickupLocation(button) {
        super._updatePickupLocation(...arguments);
        const dmContainer = this._getDeliveryMethodContainer(button);
        const radio = dmContainer.querySelector('[name="o_delivery_radio"]');
        if (radio.dataset.deliveryType === "in_store") {
            dmContainer
                .querySelector('[name="unavailable_products_warning"]')
                ?.remove();
        }
    },

    /**
     * @override
     */
    _isDeliveryMethodReady() {
        if (this.dmRadios.length === 0) {
            return super._isDeliveryMethodReady(...arguments);
        }
        const checkedRadio = this.el.querySelector(
            'input[name="o_delivery_radio"]:checked',
        );
        let hasWarning = false;
        if (checkedRadio) {
            const deliveryContainer = this._getDeliveryMethodContainer(checkedRadio);
            hasWarning =
                checkedRadio.dataset.deliveryType === "in_store" &&
                deliveryContainer.querySelector(
                    '[name="unavailable_products_warning"]',
                );
        }
        return super._isDeliveryMethodReady(...arguments) && !hasWarning;
    },

    /**
     * @override
     */
    _hidePickupLocation() {
        super._hidePickupLocation(...arguments);
        const warning = this.el.querySelector('[name="unavailable_products_warning"]');
        if (warning) {
            warning.classList.add("d-none");
        }
    },

    /**
     * @override
     */
    async _showPickupLocation(radio) {
        super._showPickupLocation(...arguments);
        if (radio.dataset.deliveryType === "in_store") {
            const dmContainer = this._getDeliveryMethodContainer(radio);
            const warning = dmContainer.querySelector(
                '[name="unavailable_products_warning"]',
            );
            if (warning) {
                warning.classList.remove("d-none");
            }
        }
    },
});
