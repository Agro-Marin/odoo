/** @odoo-module native */

/** @module @l10n_tw_edi_ecpay_website_sale/interactions/invoicing_info - ECPay invoicing info form (carrier / love code validation) */

import { WarningDialog } from "@web/components/errors";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

const LOVE_CODE_RE = /^([xX]{1}[0-9]{2,6}|[0-9]{3,7})$/;
const MOBILE_BARCODE_RE = /^\/[0-9a-zA-Z+-.]{7}$/;

export class EcpayInvoicingInfo extends Interaction {
    static selector = ".o_l10n_tw_edi_invoicing_info";
    dynamicContent = {
        "#l10n_tw_edi_is_donate": { "t-on-change": this.onChangeDonateCheckbox },
        "#l10n_tw_edi_carrier_type": { "t-on-change": this.onChangeCarrierType },
        "#l10n_tw_edi_carrier_number": { "t-on-input": this.onInputCarrierNumber },
        "#l10n_tw_edi_love_code": { "t-on-input": this.onInputLoveCode },
        "#validate_carrier_number": {
            "t-on-click": this.locked(this.onClickValidateCarrierNumber, true),
            "t-att-class": () => ({ "d-none": !this.showValidateCarrierNumber }),
        },
        "#validate_love_code": {
            "t-on-click": this.locked(this.onClickValidateLoveCode, true),
            "t-att-class": () => ({ "d-none": !this.showValidateLoveCode }),
        },
        "#reenter_carrier_number": {
            "t-on-click": this.onClickReenterCarrierNumber,
            "t-att-class": () => ({ "d-none": !this.showReenterCarrierNumber }),
        },
        "#reenter_love_code": {
            "t-on-click": this.onClickReenterLoveCode,
            "t-att-class": () => ({ "d-none": !this.showReenterLoveCode }),
        },
        "#ecpay_invoice_love_code": {
            "t-att-class": () => ({ "d-none": !this.showLoveCode }),
        },
        "#ecpay_carrier_type_group": {
            "t-att-class": () => ({ "d-none": !this.showCarrierType }),
        },
        "#ecpay_invoice_carrier_number": {
            "t-att-class": () => ({ "d-none": !this.showCarrier }),
        },
        "#ecpay_invoice_carrier_number_2": {
            "t-att-class": () => ({ "d-none": !this.showCarrier2 }),
        },
    };

    setup() {
        // Mirror the server-rendered visibility so the first dynamicContent
        // application is a no-op when the invoice method block is absent.
        const hidden = (sel) =>
            !!this.el.querySelector(sel)?.classList.contains("d-none");
        this.showLoveCode = !hidden("#ecpay_invoice_love_code");
        this.showCarrierType = !hidden("#ecpay_carrier_type_group");
        this.showCarrier = !hidden("#ecpay_invoice_carrier_number");
        this.showCarrier2 = !hidden("#ecpay_invoice_carrier_number_2");
        this.showReenterCarrierNumber = !hidden("#reenter_carrier_number");
        this.showReenterLoveCode = !hidden("#reenter_love_code");
        this.validCarrierNumber = false;
        this.validLoveCode = false;
        if (document.querySelector("#ecpay_invoice_method")) {
            this.showValidateCarrierNumber =
                this.el.querySelector("#l10n_tw_edi_carrier_type")?.value === "3";
            this.showValidateLoveCode = this.showLoveCode;
        } else {
            this.showValidateCarrierNumber = !hidden("#validate_carrier_number");
            this.showValidateLoveCode = !hidden("#validate_love_code");
        }
    }

    getTokenInfo() {
        const form = document.getElementById("form_l10n_tw_invoicing_info");
        const saleOrderId = form.getAttribute("date-order-id");
        const accessToken = form.getAttribute("data-access-token");
        return { saleOrderId, accessToken };
    }

    onChangeDonateCheckbox(ev) {
        const isChecked = ev.target.checked;
        this.showLoveCode = isChecked;
        this.showValidateLoveCode = isChecked && !this.validLoveCode;
        this.showReenterLoveCode = isChecked && this.validLoveCode;
        const loveCodeInput = this.el.querySelector("#l10n_tw_edi_love_code");
        this.el.querySelector("#validate_love_code").disabled = !LOVE_CODE_RE.test(
            loveCodeInput.value,
        );
        this.showCarrierType = !isChecked;
    }

    onChangeCarrierType(ev) {
        const carrierType = ev.target.value;
        const carrierNumberField = this.el.querySelector("#l10n_tw_edi_carrier_number");
        if (carrierType === "2") {
            carrierNumberField.placeholder = _t("Example: TP03000001234567");
            this.showCarrier = true;
            this.showCarrier2 = false;
            this.showValidateCarrierNumber = false;
            this.showReenterCarrierNumber = false;
        } else if (carrierType === "3") {
            carrierNumberField.placeholder = _t("Example: /ABCD123");
            this.showCarrier = true;
            this.showCarrier2 = false;
            this.showValidateCarrierNumber = !this.validCarrierNumber;
            this.showReenterCarrierNumber = this.validCarrierNumber;
            this.el.querySelector("#validate_carrier_number").disabled =
                !MOBILE_BARCODE_RE.test(carrierNumberField.value);
        } else if (["4", "5"].includes(carrierType)) {
            this.showCarrier = true;
            this.showCarrier2 = true;
            this.showValidateCarrierNumber = false;
            this.showReenterCarrierNumber = false;
            carrierNumberField.placeholder = _t("Card hidden code");
            this.el.querySelector("#l10n_tw_edi_carrier_number_2").placeholder =
                _t("Card visible code");
        } else {
            this.showCarrier = false;
            this.showCarrier2 = false;
            this.showValidateCarrierNumber = false;
            this.showReenterCarrierNumber = false;
        }
        this.validCarrierNumber = false;
    }

    onInputCarrierNumber(ev) {
        const carrierType = this.el.querySelector("#l10n_tw_edi_carrier_type").value;
        if (carrierType === "2") {
            this.validCarrierNumber = /^[A-Z]{2}[0-9]{14}$/.test(ev.target.value);
        } else if (carrierType === "3") {
            this.el.querySelector("#validate_carrier_number").disabled =
                !MOBILE_BARCODE_RE.test(ev.target.value);
        }
    }

    onInputLoveCode(ev) {
        this.validLoveCode = false;
        this.el.querySelector("#validate_love_code").disabled = !LOVE_CODE_RE.test(
            ev.target.value,
        );
    }

    async onClickValidateCarrierNumber() {
        try {
            const { saleOrderId, accessToken } = this.getTokenInfo();
            const result = await this.waitFor(
                rpc("/payment/ecpay/check_mobile_barcode/" + saleOrderId, {
                    access_token: accessToken,
                    carrier_number: this.el.querySelector("#l10n_tw_edi_carrier_number")
                        .value,
                }),
            );
            if (result) {
                this.validCarrierNumber = true;
                this.showValidateCarrierNumber = false;
                this.showReenterCarrierNumber = true;
                this.el.querySelector("#l10n_tw_edi_carrier_type").disabled = true;
                this.el
                    .querySelector("#l10n_tw_edi_carrier_number")
                    .setAttribute("readonly", true);
            } else {
                this.services.dialog.add(WarningDialog, {
                    title: _t("Error"),
                    message: _t("Carrier number is invalid"),
                });
            }
        } catch (error) {
            this.services.dialog.add(WarningDialog, {
                title: _t("ECpay Error"),
                message: error.data.message,
            });
        }
    }

    async onClickValidateLoveCode() {
        try {
            const { saleOrderId, accessToken } = this.getTokenInfo();
            const result = await this.waitFor(
                rpc("/payment/ecpay/check_love_code/" + saleOrderId, {
                    access_token: accessToken,
                    love_code: this.el.querySelector("#l10n_tw_edi_love_code").value,
                }),
            );
            if (result) {
                this.validLoveCode = true;
                this.showValidateLoveCode = false;
                this.showReenterLoveCode = true;
                this.el
                    .querySelector("#l10n_tw_edi_love_code")
                    .setAttribute("readonly", true);
            } else {
                this.services.dialog.add(WarningDialog, {
                    title: _t("Error"),
                    message: _t("Love code is invalid"),
                });
            }
        } catch (error) {
            this.services.dialog.add(WarningDialog, {
                title: _t("ECpay Error"),
                message: error.data.message,
            });
        }
    }

    onClickReenterCarrierNumber() {
        this.validCarrierNumber = false;
        this.showValidateCarrierNumber = true;
        this.showReenterCarrierNumber = false;
        this.el.querySelector("#l10n_tw_edi_carrier_type").disabled = false;
        this.el
            .querySelector("#l10n_tw_edi_carrier_number")
            .removeAttribute("readonly");
    }

    onClickReenterLoveCode() {
        this.validLoveCode = false;
        this.showValidateLoveCode = true;
        this.showReenterLoveCode = false;
        this.el.querySelector("#l10n_tw_edi_love_code").removeAttribute("readonly");
    }
}

registry
    .category("public.interactions")
    .add("l10n_tw_edi_ecpay_website_sale.invoicing_info", EcpayInvoicingInfo);
