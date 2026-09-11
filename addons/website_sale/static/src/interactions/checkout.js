/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { rpc } from "@web/core/network";
import { LocationSelectorDialog } from "@delivery/js/location_selector/location_selector_dialog/location_selector_dialog";

export class Checkout extends Interaction {
    static selector = "#shop_checkout";
    dynamicContent = {
        ".card": { "t-on-click": this.changeAddress },
        ".js_edit_address": { "t-on-click.stop": () => {} },
        "#use_delivery_as_billing": { "t-on-change": this.toggleBillingAddressRow },
        '[name="o_delivery_radio"]': { "t-on-click": this.selectDeliveryMethod },
        '[name="o_pickup_location_selector"]': {
            "t-on-click": this.selectPickupLocation,
        },
    };

    setup() {
        this.mainButton = Array.from(
            document.getElementsByName("website_sale_main_button"),
        ).find((button) => button.offsetParent !== null);
        this.useDeliveryAsBillingToggle = document.querySelector(
            "#use_delivery_as_billing",
        );
        this.billingContainer = this.el.querySelector("#billing_container");
        this.addBillingAddressBtn = this.el.querySelector(".o_add_billing_address_btn");
    }

    async willStart() {
        await this.waitFor(this._prepareDeliveryMethods());
    }

    async start() {
        const boundOnNavigationBack = this._onNavigationBack.bind(this);
        window.addEventListener("pageshow", boundOnNavigationBack);
        this.registerCleanup(() =>
            window.removeEventListener("pageshow", boundOnNavigationBack),
        );
    }

    /**
     * @param {PageTransitionEvent} event
     * @private
     */
    _onNavigationBack(event) {
        if (event.persisted) {
            window.location.reload();
        }
    }

    /**
     * @param {Event} ev
     * @return {void}
     */
    async changeAddress(ev) {
        const newAddress = ev.currentTarget;
        if (newAddress.classList.contains("bg-400")) {
            return;
        }
        const addressType = newAddress.dataset.addressType;

        const previousAddress = this._getSelectedAddress(addressType);
        this._tuneDownAddressCard(previousAddress);

        this._highlightAddressCard(newAddress);
        const selectedPartnerId = newAddress.dataset.partnerId;
        await this.waitFor(this.updateAddress(addressType, selectedPartnerId));
        if (
            addressType === "delivery" ||
            this.billingContainer.dataset.deliveryAddressDisabled
        ) {
            if (this.billingContainer.dataset.deliveryAddressDisabled) {
                await this.waitFor(this.updateAddress("delivery", selectedPartnerId));
            }
            if (this.useDeliveryAsBillingToggle?.checked) {
                await this.waitFor(
                    this._selectMatchingBillingAddress(selectedPartnerId),
                );
            }
            const deliveryFormHtml = await this.waitFor(rpc("/shop/delivery_methods"));
            this.services["public.interactions"].stopInteractions(this.el);
            document.getElementById("o_delivery_form").innerHTML = deliveryFormHtml;
            this.services["public.interactions"].startInteractions(this.el);
            await this.waitFor(this._prepareDeliveryMethods());
        }
        this._enableMainButton();
    }

    /**
     * @param ev
     * @return {void}
     */
    async toggleBillingAddressRow(ev) {
        const useDeliveryAsBilling = ev.target.checked;

        const addDeliveryAddressButton = this.el.querySelector(
            '.o_address_card_add_new[data-address-type="delivery"]',
        );
        if (addDeliveryAddressButton) {
            const addDeliveryUrl = new URL(addDeliveryAddressButton.href);
            addDeliveryUrl.searchParams.set(
                "use_delivery_as_billing",
                encodeURIComponent(useDeliveryAsBilling),
            );
            addDeliveryAddressButton.href = addDeliveryUrl.toString();
        }

        if (useDeliveryAsBilling) {
            this.billingContainer.classList.add("d-none");
            const selectedDeliveryAddress = this._getSelectedAddress("delivery");
            await this.waitFor(
                this._selectMatchingBillingAddress(
                    selectedDeliveryAddress.dataset.partnerId,
                ),
            );
        } else {
            this._disableMainButton();
            this.billingContainer.classList.remove("d-none");
        }
        this.addBillingAddressBtn.classList.toggle("d-none", useDeliveryAsBilling);

        this._enableMainButton();
    }

    /**
     * @param {Event} ev
     * @return {void}
     */
    async selectDeliveryMethod(ev) {
        const checkedRadio = ev.currentTarget;
        if (checkedRadio.disabled) {
            return;
        }

        this._disableMainButton();

        this._hidePickupLocation();

        await this.waitFor(this._updateDeliveryMethod(checkedRadio));

        this._enableMainButton();

        await this._showPickupLocation(checkedRadio);
    }

    /**
     * @param {Event} ev
     * @return {void}
     */
    async selectPickupLocation(ev) {
        const { zipCode, locationId } = ev.currentTarget.dataset;
        const deliveryMethodContainer = this._getDeliveryMethodContainer(
            ev.currentTarget,
        );
        this.services.dialog.add(LocationSelectorDialog, {
            zipCode: zipCode,
            selectedLocationId: locationId,
            isFrontend: true,
            save: async (location) => {
                const jsonLocation = JSON.stringify(location);
                await this.waitFor(this._setPickupLocation(jsonLocation));

                this._updatePickupLocation(
                    deliveryMethodContainer,
                    location,
                    jsonLocation,
                );

                this._enableMainButton();
            },
        });
    }

    /**
     * @private
     * @param deliveryMethodContainer
     * @param location
     * @param jsonLocation
     * @return {void}
     */
    _updatePickupLocation(deliveryMethodContainer, location, jsonLocation) {
        const pickupLocation = deliveryMethodContainer.querySelector(
            '[name="o_pickup_location"]',
        );
        pickupLocation.querySelector('[name="o_pickup_location_name"]').innerText =
            location.name;
        pickupLocation.querySelector('[name="o_pickup_location_address"]').innerText =
            `${location.street} ${location.zip_code} ${location.city}`;
        const editPickupLocationButton = pickupLocation.querySelector(
            'span[name="o_pickup_location_selector"]',
        );
        editPickupLocationButton.dataset.locationId = location.id;
        editPickupLocationButton.dataset.zipCode = location.zip_code;
        editPickupLocationButton.dataset.pickupLocationData = jsonLocation;
        pickupLocation
            .querySelector('[name="o_pickup_location_details"]')
            .classList.remove("d-none");

        pickupLocation
            .querySelector('button[name="o_pickup_location_selector"]')
            ?.remove();
    }

    /**
     * @private
     * @param card
     * @return {void}
     */
    _tuneDownAddressCard(card) {
        if (!card) return;
        card.classList.remove("bg-400", "border", "border-primary");
    }

    /**
     * @private
     * @param card
     * @return {void}
     */
    _highlightAddressCard(card) {
        if (!card) return;
        card.classList.add("bg-400", "border", "border-primary");
    }

    /**
     * @private
     * @return {void}
     */
    _disableMainButton() {
        this.mainButton?.classList.add("disabled");
    }

    /**
     * @private
     * @return {void}
     */
    _enableMainButton() {
        if (this._canEnableMainButton()) {
            this.mainButton?.classList.remove("disabled");
        }
    }

    /**
     * @private
     * @return {boolean}
     */
    _canEnableMainButton() {
        return this._isDeliveryMethodReady() && this._isBillingAddressSelected();
    }

    /**
     * @private
     * @return {void}
     */
    _hidePickupLocation() {
        const pickupLocations = document.querySelectorAll(
            '[name="o_pickup_location"]:not(.d-none)',
        );
        pickupLocations.forEach((pickupLocation) =>
            pickupLocation.classList.add("d-none"),
        );
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {void}
     */
    async _updateDeliveryMethod(radio) {
        this._showLoadingBadge(radio);
        const result = await this.waitFor(this._setDeliveryMethod(radio.dataset.dmId));
        this._updateAmountBadge(radio, result);
        this._updateCartSummaries(result);
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {void}
     */
    _showLoadingBadge(radio) {
        const deliveryPriceBadge = this._getDeliveryPriceBadge(radio);
        this._clearElement(deliveryPriceBadge);
        deliveryPriceBadge.appendChild(this._createLoadingElement());
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @param {Object} rateData
     * @return {void}
     */
    _updateAmountBadge(radio, rateData) {
        const deliveryPriceBadge = this._getDeliveryPriceBadge(radio);
        if (rateData.success) {
            if (rateData.compute_price_after_delivery) {
                deliveryPriceBadge.textContent = _t("Computed after delivery");
            } else if (rateData.is_free_delivery) {
                deliveryPriceBadge.textContent = _t("Free");
            } else {
                deliveryPriceBadge.innerHTML = rateData.amount_delivery;
            }
            this._toggleDeliveryMethodRadio(radio);
        } else {
            deliveryPriceBadge.textContent = rateData.error_message;
            this._toggleDeliveryMethodRadio(radio, true);
        }
    }

    /**
     * @private
     * @param {Object} result
     * @param {Object} targetEl
     * @return {void}
     */
    _updateCartSummary(result, targetEl) {
        const amountDelivery = targetEl.querySelector(
            'tr[name="o_order_delivery"] .monetary_field',
        );
        const amountUntaxed = targetEl.querySelector(
            'tr[name="o_order_total_untaxed"] .monetary_field',
        );
        const amountTax = targetEl.querySelector(
            'tr[name="o_order_total_taxes"] .monetary_field',
        );
        const amountTotal = targetEl.parentElement.querySelectorAll(
            'tr[name="o_order_total"] .monetary_field, #amount_total_summary.monetary_field',
        );

        if (amountDelivery.classList.contains("d-none")) {
            amountDelivery
                .querySelector('span[name="o_message_no_dm_set"]')
                ?.classList.add("d-none");
            amountDelivery.classList.remove("d-none");
        }

        amountDelivery.innerHTML = result.amount_delivery;
        amountUntaxed.innerHTML = result.amount_untaxed;
        amountTax.innerHTML = result.amount_tax;
        amountTotal.forEach((total) => (total.innerHTML = result.amount_total));
    }

    /**
     * @private
     * @param {Object} result
     * @return {void}
     */
    _updateCartSummaries(result) {
        const parentElements = document.querySelectorAll(
            "#o_cart_summary_offcanvas, div.o_total_card",
        );
        parentElements.forEach((el) => this._updateCartSummary(result, el));
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @param {Boolean} disable
     */
    _toggleDeliveryMethodRadio(radio, disable = false) {
        const deliveryPriceBadge = this._getDeliveryPriceBadge(radio);
        radio.disabled = disable;
        if (disable) {
            deliveryPriceBadge.classList.add("text-muted");
        } else {
            deliveryPriceBadge.classList.remove("text-muted");
        }
    }

    /**
     * @private
     * @param {Element} el
     * @return {void}
     */
    _clearElement(el) {
        while (el.firstChild) {
            el.removeChild(el.lastChild);
        }
    }

    /**
     * @private
     * @param selectedPartnerId
     * @return {void}
     */
    async _selectMatchingBillingAddress(selectedPartnerId) {
        const previousAddress = this._getSelectedAddress("billing");
        this._tuneDownAddressCard(previousAddress);
        await this.waitFor(this.updateAddress("billing", selectedPartnerId));
        const billingAddress = this.el.querySelector(
            `.card[data-partner-id="${selectedPartnerId}"][data-address-type="billing"]`,
        );
        this._highlightAddressCard(billingAddress);
    }

    /**
     * @param addressType
     * @param partnerId
     * @return {void}
     */
    async updateAddress(addressType, partnerId) {
        await rpc("/shop/update_address", {
            address_type: addressType,
            partner_id: partnerId,
        });
    }

    /**
     * @private
     * @return {void}
     */
    async _prepareDeliveryMethods() {
        this.dmRadios = Array.from(
            document.querySelectorAll('input[name="o_delivery_radio"]'),
        );
        if (this.dmRadios.length > 0) {
            const checkedRadio = document.querySelector(
                'input[name="o_delivery_radio"]:checked',
            );
            this._disableMainButton();
            if (checkedRadio) {
                await this.waitFor(this._updateDeliveryMethod(checkedRadio));
                this._enableMainButton();
                await this._showPickupLocation(checkedRadio);
            }
        }
        await Promise.all(
            this.dmRadios
                .filter((radio) => !radio.checked)
                .map(async (radio) => {
                    this._showLoadingBadge(radio);
                    const rateData = await this.waitFor(this._getDeliveryRate(radio));
                    this._updateAmountBadge(radio, rateData);
                }),
        );
    }

    /**
     * @private
     * @return {boolean}
     */
    _isDeliveryMethodReady() {
        if (this.dmRadios.length === 0) {
            return true;
        }
        const checkedRadio = document.querySelector(
            'input[name="o_delivery_radio"]:checked',
        );
        return (
            checkedRadio &&
            !checkedRadio.disabled &&
            !this._isPickupLocationMissing(checkedRadio)
        );
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {Object}
     */
    async _getDeliveryRate(radio) {
        return await rpc("/shop/get_delivery_rate", { dm_id: radio.dataset.dmId });
    }

    /**
     * @private
     * @param {Integer} dmId
     * @return {Object}
     */
    async _setDeliveryMethod(dmId) {
        return await rpc("/shop/set_delivery_method", { dm_id: dmId });
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {void}
     */
    async _showPickupLocation(radio) {
        if (!radio.dataset.isPickupLocationRequired || radio.disabled) {
            return;
        }
        const deliveryMethodContainer = this._getDeliveryMethodContainer(radio);
        const pickupLocation = deliveryMethodContainer.querySelector(
            '[name="o_pickup_location"]',
        );

        const editPickupLocationButton = pickupLocation.querySelector(
            'span[name="o_pickup_location_selector"]',
        );
        if (editPickupLocationButton.dataset.pickupLocationData) {
            await this.waitFor(
                this._setPickupLocation(
                    editPickupLocationButton.dataset.pickupLocationData,
                ),
            );
        }

        pickupLocation.classList.remove("d-none");
    }

    /**
     * @private
     * @param {String} pickupLocationData
     * @return {void}
     */
    async _setPickupLocation(pickupLocationData) {
        await rpc("/website_sale/set_pickup_location", {
            pickup_location_data: pickupLocationData,
        });
    }

    /**
     * @private
     * @param addressType
     * @return {Element}
     */
    _getSelectedAddress(addressType) {
        return this.el.querySelector(
            `.card.bg-400[data-address-type="${addressType}"]`,
        );
    }

    /**
     * @private
     * @return {boolean}
     */
    _isBillingAddressSelected() {
        const billingAddressSelected = Boolean(
            this.el.querySelector('.card.bg-400[data-address-type="billing"]'),
        );
        return billingAddressSelected || this.useDeliveryAsBillingToggle?.checked;
    }

    /**
     * @private
     * @return {Element}
     */
    _createLoadingElement() {
        const loadingElement = document.createElement("i");
        loadingElement.classList.add(
            "fa-solid",
            "fa-circle-notch",
            "fa-spin",
            "center",
        );
        return loadingElement;
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {Element}
     */
    _getDeliveryPriceBadge(radio) {
        const deliveryMethodContainer = this._getDeliveryMethodContainer(radio);
        return deliveryMethodContainer.querySelector(".o_wsale_delivery_price_badge");
    }

    /**
     * @private
     * @param {Element} el
     * @return {Element}
     */
    _getDeliveryMethodContainer(el) {
        return el.closest('[name="o_delivery_method"]');
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {boolean}
     */
    _isPickupLocationMissing(radio) {
        const deliveryMethodContainer = this._getDeliveryMethodContainer(radio);
        if (!this._isPickupLocationRequired(radio)) return false;
        return !deliveryMethodContainer.querySelector(
            'span[name="o_pickup_location_selector"]',
        ).dataset.locationId;
    }

    /**
     * @private
     * @param {HTMLInputElement} radio
     * @return {bool}
     */
    _isPickupLocationRequired(radio) {
        return Boolean(radio.dataset.isPickupLocationRequired);
    }
}

registry.category("public.interactions").add("website_sale.checkout", Checkout);
