// @ts-check
/** @odoo-module native */

import { Component, useRef, useState } from "@odoo/owl";
import { Transition } from "@web/core/transition";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

const RENEWAL_GRACE_DAYS = 15;

/**
 * @param {number} days
 * @returns {string}
 */
function dayCount(days) {
    return days === 1 ? _t("1 day") : _t("%s days", days);
}

/** @extends */
export class ExpirationPanel extends Component {
    static template = "web.ExpirationPanel";
    static props = {};
    static components = { Transition };

    /** @type {import("services").ServiceFactories["enterprise_subscription"]} */
    subscription;
    /** @type {{ displayRegisterForm: boolean }} */
    state;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    inputRef;

    setup() {
        this.subscription = useService("enterprise_subscription");

        this.state = useState({
            displayRegisterForm: false,
        });

        this.inputRef = useRef("input");
    }

    get buttonText() {
        return this.subscription.lastRequestStatus === "error"
            ? _t("Retry")
            : _t("Register");
    }

    get alertType() {
        if (this.subscription.lastRequestStatus === "success") {
            return "success";
        }
        const { daysLeft } = this.subscription;
        if (daysLeft <= 6) {
            return "danger";
        } else if (daysLeft <= 16) {
            return "warning";
        }
        return "info";
    }

    get expirationMessage() {
        const { daysLeft } = this.subscription;
        if (daysLeft <= 0) {
            return _t("This database has expired. ");
        }
        const delay = daysLeft === 30 ? _t("1 month") : dayCount(daysLeft);
        if (this.subscription.expirationReason === "demo") {
            return _t("This demo database will expire in %s. ", delay);
        }
        if (this.subscription.expirationReason !== "renewal") {
            return _t("This database will expire in %s. ", delay);
        }
        if (daysLeft > RENEWAL_GRACE_DAYS) {
            return _t(
                "Your subscription expires in %s. ",
                dayCount(daysLeft - RENEWAL_GRACE_DAYS),
            );
        }
        return _t(
            "Your subscription expired %s ago. This database will be blocked soon. ",
            dayCount(RENEWAL_GRACE_DAYS - daysLeft),
        );
    }

    showRegistrationForm() {
        this.state.displayRegisterForm = !this.state.displayRegisterForm;
    }

    async onCodeSubmit() {
        const enterpriseCode = /** @type {HTMLInputElement} */ (this.inputRef.el).value;
        if (!enterpriseCode) {
            return;
        }
        await this.subscription.submitCode(enterpriseCode);
        if (this.subscription.lastRequestStatus === "success") {
            this.state.displayRegisterForm = false;
        }
    }
}
