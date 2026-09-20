/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Tooltip, Modal } from "@web/libs/bootstrap";
import { patchDynamicContent } from "@web/public/utils";
import { rpc } from "@web/core/network";
import { Checkout } from "@website_sale/interactions/checkout";

import { registry } from "@web/core/registry";
import { ThirdPartyScriptError } from "@web/core/errors/error_service";
const errorHandlerRegistry = registry.category("error_handlers");

function corsIgnoredErrorHandler(env, error) {
    if (error instanceof ThirdPartyScriptError) {
        return true;
    }
}

patch(Checkout.prototype, {
    setup() {
        super.setup();
        patchDynamicContent(this.dynamicContent, {
            "#btn_confirm_relay": {
                "t-on-click": this.onClickBtnConfirmRelay.bind(this),
            },
        });
        this.mondialRelayModal = undefined;
        this.useDeliveryAsBillingTooltip = undefined;
        const useDeliveryAsBillingLabel = this.el.querySelector(
            "#use_delivery_as_billing_label",
        );
        if (useDeliveryAsBillingLabel) {
            this.useDeliveryAsBillingTooltip = Tooltip.getOrCreateInstance(
                useDeliveryAsBillingLabel,
            );
            this.registerCleanup(() => this.useDeliveryAsBillingTooltip.dispose());
        }
        this._adaptUseDeliveryAsBillingToggle();
    },

    /**
     * @override
     */
    async selectDeliveryMethod(ev) {
        const checkedRadio = ev.currentTarget;
        await this.waitFor(super.selectDeliveryMethod(...arguments));
        if (checkedRadio.dataset.isMondialrelay) {
            if (this.useDeliveryAsBillingToggle?.checked) {
                this.useDeliveryAsBillingToggle.dispatchEvent(new MouseEvent("click"));
            }
            const result = await this.waitFor(
                this._setDeliveryMethod(checkedRadio.dataset.dmId),
            );
            if (!this.mondialRelayModal) {
                this._loadMondialRelayModal(result);
            } else {
                this.mondialRelayModal
                    .querySelector("#btn_confirm_relay")
                    .classList.toggle("disabled", !result.mondial_relay.current);
                Modal.getOrCreateInstance(this.mondialRelayModal).show();
            }
        }
        this._adaptUseDeliveryAsBillingToggle();
    },

    /**
     * @override
     */
    async changeAddress(ev) {
        const newAddress = ev.currentTarget;
        if (
            newAddress.dataset.isMondialrelay &&
            this.useDeliveryAsBillingToggle?.checked
        ) {
            this.useDeliveryAsBillingToggle.dispatchEvent(new MouseEvent("click"));
        }
        await this.waitFor(super.changeAddress(...arguments));
        this._adaptUseDeliveryAsBillingToggle();
    },

    /**
     * @private
     * @return {void}
     */
    _adaptUseDeliveryAsBillingToggle() {
        if (this.useDeliveryAsBillingToggle) {
            const checkedRadio = document.querySelector(
                'input[name="o_delivery_radio"]:checked',
            );
            const selectedDeliveryAddress = this._getSelectedAddress("delivery");
            const requireSeparateBillingAddress =
                checkedRadio?.dataset.isMondialrelay ||
                selectedDeliveryAddress?.dataset.isMondialrelay;
            this.useDeliveryAsBillingToggle.disabled = requireSeparateBillingAddress;
            requireSeparateBillingAddress
                ? this.useDeliveryAsBillingTooltip?.enable()
                : this.useDeliveryAsBillingTooltip?.disable();
        }
    },

    /**
     * @private
     * @param {Object} result
     */
    _loadMondialRelayModal(result) {
        this.renderAt("website_sale_mondialrelay", {}, document.querySelector("body"));
        this.mondialRelayModal = document.querySelector("#modal_mondialrelay");
        this.mondialRelayModal
            .querySelector("#btn_confirm_relay")
            .addEventListener("click", this.onClickBtnConfirmRelay.bind(this));

        const loadScript = (url) =>
            new Promise((resolve) => {
                const s = document.createElement("script");
                s.src = url;
                s.onload = resolve;
                document.body.appendChild(s);
            });
        const jqueryPromise = window.jQuery
            ? Promise.resolve()
            : loadScript("/delivery_mondialrelay/static/lib/jquery.slim.min.js");
        jqueryPromise
            .then(() =>
                loadScript(
                    "https://widget.mondialrelay.com/parcelshop-picker/jquery.plugin.mondialrelay.parcelshoppicker.min.js",
                ),
            )
            .then(() => {
                const params = {
                    Target: "",
                    Brand: result.mondial_relay.brand,
                    ColLivMod: result.mondial_relay.col_liv_mod,
                    AllowedCountries: result.mondial_relay.allowed_countries,
                    Country: result.mondial_relay.partner_country_code,
                    PostCode: result.mondial_relay.partner_zip,
                    Responsive: true,
                    ShowResultsOnMap: true,
                    AutoSelect: result.mondial_relay.current,
                    OnParcelShopSelected: (RelaySelected) => {
                        this.lastRelaySelected = RelaySelected;
                        this.mondialRelayModal
                            .querySelector("#btn_confirm_relay")
                            .classList.remove("disabled");
                    },
                    OnNoResultReturned: () => {
                        const randInt = Math.floor(Math.random() * 100);
                        errorHandlerRegistry.add(
                            "corsIgnoredErrorHandler" + randInt,
                            corsIgnoredErrorHandler,
                            { sequence: 10 },
                        );
                        this.waitForTimeout(
                            () =>
                                errorHandlerRegistry.remove(
                                    "corsIgnoredErrorHandler" + randInt,
                                ),
                            10000,
                        );
                    },
                };
                const zoneWidget =
                    this.mondialRelayModal.querySelector("#o_zone_widget");
                window.jQuery(zoneWidget).MR_ParcelShopPicker(params);
                Modal.getOrCreateInstance(this.mondialRelayModal).show();
                window.jQuery(zoneWidget).trigger("MR_RebindMap");
            });
    },

    async onClickBtnConfirmRelay() {
        if (!this.lastRelaySelected) return;
        await this.waitFor(
            rpc("/website_sale_mondialrelay/update_shipping", {
                ...this.lastRelaySelected,
            }),
        );
        location.reload();
    },
});
