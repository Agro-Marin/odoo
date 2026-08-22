/* global posmodel */

import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as NumberPopup from "@point_of_sale/../tests/generic_helpers/number_popup_util";
import * as Numpad from "@point_of_sale/../tests/generic_helpers/numpad_util";
import * as PartnerList from "@point_of_sale/../tests/pos/tours/utils/partner_list_util";

/**
 * @param {string} name
 * @param {boolean} [isCheckNeeded=false]
 * @param {Object} [options={}]
 * @param {string|null} [options.remaining=null]
 * @param {string|null} [options.change=null]
 * @param {string|null} [options.amount=null]
 */
export function clickPaymentMethod(name, isCheckNeeded = false, options = {}) {
    const { remaining = null, change = null, amount = null } = options;

    const step = [
        {
            content: `click '${name}' payment method`,
            trigger: `.paymentmethods .button.paymentmethod .payment-name:contains("${name}")`,
            run: "click",
        },
    ];

    if (isCheckNeeded) {
        if (remaining) {
            step.push(...remainingIs(remaining));
        }
        if (change) {
            step.push(...changeIs(change));
        }
        if (amount) {
            step.push(...selectedPaymentlineHas(name, amount));
        }
    }

    return step;
}
/**
 * @param {String} name
 * @param {String} amount
 */
export function clickPaymentlineDelButton(name, amount, mobile = false) {
    return [
        {
            content: `delete ${name} paymentline with ${amount} amount`,
            trigger: `.paymentlines .paymentline .payment-infos:contains("${name}"):has(.payment-amount:contains("${amount}")) ~ .delete-button`,
            run: "click",
        },
    ];
}
export function clickCancelButton() {
    return [
        {
            content: "Cancel the ongoing payment request currently being processed.",
            trigger: ".paymentlines .paymentline .send_payment_cancel",
            run: "click",
        },
    ];
}
export function clickRetryButton() {
    return [
        {
            content: "Retry sending the payment request using the payment terminal.",
            trigger:
                ".paymentlines .paymentline .send_payment_request:contains('Retry')",
            run: "click",
        },
    ];
}
export function clickRefundButton() {
    return [
        {
            content: "Initiate a refund request for the selected order.",
            trigger: ".paymentlines .send_refund_request:contains('Refund')",
            run: "click",
        },
    ];
}
/**
 * @param {String} name
 * @param {String} amount
 */
export function clickPaymentline(name, amount) {
    return [
        {
            content: `click ${name} paymentline with ${amount} amount`,
            trigger: `.paymentlines .paymentline .payment-infos:contains("${name}"):has(.payment-amount:contains("${amount}"))`,
            run: "click",
        },
    ];
}
export function clickInvoiceButton() {
    return [
        {
            content: "click invoice button",
            trigger: ".payment-buttons .js_invoice",
            run: "click",
        },
    ];
}
export function clickValidate() {
    return [
        {
            content: "validate payment",
            trigger: `.payment-screen button.validation-button.next`,
            run: "click",
        },
    ];
}
/**
 * @param {String} keys
 */
export function clickNumpad(keys) {
    return keys
        .split(" ")
        .map((key) => ({ ...Numpad.click(key), isActive: ["desktop"] }));
}
export function clickBack() {
    return [
        {
            content: "click back button",
            trigger: ".back-button",
            run: "click",
        },
    ];
}
export function clickBackToProductScreen() {
    return [
        {
            content: "click back to product screen",
            trigger: ".payment-screen .back-button",
            run: "click",
        },
    ];
}
export function clickTipButton() {
    return [
        {
            trigger: ".payment-screen .button:contains('Tip')",
            run: "click",
        },
    ];
}
/**
 * @param {string} lineName
 * @param {string} keys
 * @param {boolean} [isCheckNeeded=false]
 * @param {Object} [options={}]
 * @param {string|null} [options.remaining=null]
 * @param {string|null} [options.change=null]
 * @param {string|null} [options.amount=null]
 */
export function enterPaymentLineAmount(
    lineName,
    keys,
    isCheckNeeded = false,
    options = {},
) {
    const { remaining = null, change = null, amount = null } = options;
    const step = [
        ...clickNumpad(keys.split("").join(" ")),
        ...fillPaymentLineAmountMobile(lineName, keys),
    ];

    if (isCheckNeeded) {
        if (remaining) {
            step.push(...remainingIs(remaining));
        }
        if (change) {
            step.push(...changeIs(change));
        }
        if (amount) {
            step.push(...selectedPaymentlineHas(lineName, amount));
        }
    }

    return step;
}
export function fillPaymentLineAmountMobile(lineName, keys) {
    return [
        {
            isActive: ["mobile"],
            content: "click payment line",
            trigger: `.paymentlines .paymentline .payment-infos:contains("${lineName}")`,
            run: "click",
        },
        ...NumberPopup.enterValue(keys).map((step) => ({
            ...step,
            isActive: ["mobile"],
            run: "click",
        })),
        {
            ...Dialog.confirm(),
            isActive: ["mobile"],
            run: "click",
        },
    ];
}

export function isShown() {
    return [
        {
            content: "payment screen is shown",
            trigger: ".pos .payment-screen",
        },
    ];
}
/**
 * @param {String} amount
 */
export function changeIs(amount) {
    return [
        {
            content: `change is ${amount}`,
            trigger: `.payment-status-amount .amount:contains("${amount}")`,
        },
    ];
}
export function isInvoiceOptionSelected() {
    return [
        {
            content: "Invoice option is selected",
            trigger: ".payment-buttons .js_invoice.highlight",
        },
    ];
}
/**
 * @param {String} amount
 */
export function remainingIs(amount) {
    return [
        {
            content: `remaining amount is ${amount}`,
            trigger: `.payment-status-amount .amount:contains("${amount}")`,
        },
    ];
}
/**
 * @param {Boolean} isHighlighted
 */
export function validateButtonIsHighlighted(isHighlighted = true) {
    return [
        {
            isActive: ["desktop"],
            content: `validate button is ${isHighlighted ? "highlighted" : "not highlighted"}`,
            trigger: isHighlighted
                ? `.payment-screen button.validation-button.next.highlight`
                : `.payment-screen button.validation-button.next:not(:has(.highlight))`,
        },
    ];
}
/**
 * @param {String} amountToPay
 */
export function emptyPaymentlines(amountToPay) {
    return [
        {
            content: `there are no paymentlines`,
            trigger: `.paymentlines-empty`,
        },
        {
            content: `amount to pay is '${amountToPay}'`,
            trigger: `.paymentlines-empty .total:contains("${amountToPay}")`,
        },
    ];
}
/**
 * @param {String} paymentMethodName
 * @param {String} amount
 */
export function selectedPaymentlineHas(paymentMethodName, amount) {
    return [
        {
            content: `line paid via '${paymentMethodName}' is selected`,
            trigger: `.paymentlines .paymentline.selected .payment-name:contains("${paymentMethodName}")`,
        },
        {
            content: `amount tendered in the line is '${amount}'`,
            trigger: `.paymentlines .paymentline.selected .payment-amount:contains("${amount}")`,
        },
    ];
}
export function totalIs(amount) {
    return [
        {
            content: `total is ${amount}`,
            trigger: `.total:contains("${amount}")`,
        },
    ];
}
export function pay(method, amount) {
    const steps = [];
    steps.push(...clickPaymentMethod(method));
    for (const char of amount.split("")) {
        steps.push(...clickNumpad(char));
    }
    steps.push(...validateButtonIsHighlighted());
    steps.push(...clickValidate());
    return steps;
}

export function isInvoiceButtonChecked() {
    return [
        {
            content: "check invoice button is checked",
            trigger: ".js_invoice.highlight",
        },
    ];
}

export function clickShipLaterButton() {
    return [
        {
            content: "click ship later button",
            trigger: ".button:contains('Ship Later')",
            run: "click",
        },
        {
            content: "click confirm button",
            trigger: ".btn:contains('Confirm')",
            run: "click",
        },
    ];
}

export function clickPartnerButton() {
    return [
        {
            content: "click customer button",
            trigger: "button.partner-button",
            run: "click",
        },
        {
            content: "partner screen is shown",
            trigger: `${PartnerList.clickPartner().trigger}`,
        },
    ];
}

export function clickCustomer(name, pressEnter = false) {
    return [
        ...PartnerList.searchCustomerValue(name, pressEnter),
        PartnerList.clickPartner(name),
    ];
}

export function shippingLaterHighlighted() {
    return {
        content: "Shipping later button is highlighted",
        trigger: ".button:contains('Ship Later').highlight",
    };
}

export function syncCurrentOrder() {
    return [
        {
            content: "sync current order",
            trigger: "body",
            run: async () => {
                const currentOrder = posmodel.getOrder();
                const order = await posmodel.syncAllOrders({ orders: [currentOrder] });

                if (!order[0].isSynced) {
                    throw new Error("Order ID is not a number after sync.");
                }
            },
        },
    ];
}

export function isInvoiceButtonUnchecked() {
    return [
        {
            content: "check invoice button is not highlighted",
            trigger: ".js_invoice:not(.highlight)",
        },
    ];
}
