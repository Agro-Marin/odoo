/** @odoo-module native */
import { onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { useCashierSelector } from "@pos_hr/app/utils/select_cashier_mixin";
import { _t } from "@web/core/translation";
import { useAutofocus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
patch(LoginScreen.prototype, {
    setup() {
        super.setup(...arguments);

        this.state = useState({
            pin: "",
        });

        if (this.pos.config.module_pos_hr) {
            this.cashierSelector = useCashierSelector({
                onScan: (employee) => employee && this.selectOneCashier(employee),
                exclusive: true,
            });

            useAutofocus();
            useExternalListener(window, "keypress", async (ev) => {
                if (this.pos.login && ev.key === "Enter" && this.state.pin) {
                    await this.selectCashier(this.state.pin, true);
                }
            });
        }

        onWillUnmount(() => {
            this.state.pin = "";
            this.pos.login = false;
        });
    },
    async selectCashier(pin = false, login = false, list = false) {
        return await this.cashierSelector(pin, login, list);
    },
    openRegister() {
        if (this.pos.config.module_pos_hr) {
            this.pos.login = true;
        } else {
            super.openRegister();
        }
    },
    /**
     * closePos() lands on the backend session of the logged-in user, so by
     * default leaving re-identifies the cashier and only lets that user
     * through. Deployments that accept any employee leaving override this
     * getter rather than reimplementing clickBack.
     */
    get requiresCashierIdentityToExit() {
        return true;
    },
    async clickBack() {
        if (!this.pos.config.module_pos_hr) {
            super.clickBack();
            return;
        }

        if (this.pos.login) {
            this.state.pin = "";
            this.pos.login = false;
            return;
        }

        if (!this.requiresCashierIdentityToExit) {
            super.clickBack();
            return;
        }

        const employee = await this.selectCashier();
        if (employee && employee.user_id?.id === this.pos.user.id) {
            super.clickBack();
        } else if (employee) {
            this.pos.notification.add(
                _t(
                    "Only the cashier linked to the logged-in user (%s) can proceed to the Backend.",
                    this.pos.user.name,
                ),
                { type: "danger" },
            );
        }
    },
    get backBtnName() {
        return this.pos.login && this.pos.config.module_pos_hr
            ? _t("Discard")
            : super.backBtnName;
    },
    maskedInput(ev) {
        ev.preventDefault();
        const input = ev.target;
        const pin = this.state.pin || "";
        const maskedLen = input.value.length;
        this.state.pin =
            maskedLen < pin.length ? pin.slice(0, maskedLen) : pin + (ev.data || "");

        input.value = "•".repeat(this.state.pin.length);
    },
});
