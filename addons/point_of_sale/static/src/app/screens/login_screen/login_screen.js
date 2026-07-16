/** @odoo-module native */
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useTime } from "@point_of_sale/app/hooks/time_hook";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
export class LoginScreen extends Component {
    static template = "point_of_sale.LoginScreen";
    static props = {};
    static storeOnOrder = false;
    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.ui = useService("ui");
        this.time = useTime();
    }

    openRegister() {
        this.selectUser();
    }

    selectUser() {
        this.selectOneCashier(this.pos.user);
    }
    cashierLogIn() {
        // `pos.previousScreen` is assigned nowhere since the router migration
        // — the "return to previous screen" arm could never run (and would
        // have navigated to undefined if it had: it expected a string).
        const selectedScreen = this.pos.defaultPage;
        const order = this.pos.getOrder();
        if (!order && selectedScreen.page === "ProductScreen") {
            this.pos.addNewOrder();
        }
        const params =
            selectedScreen.page === "ProductScreen"
                ? { orderUuid: this.pos.getOrder().uuid }
                : {};
        this.pos.navigate(selectedScreen.page, params);
        this.pos.hasLoggedIn = true;
    }
    selectOneCashier(cashier) {
        this.pos.setCashier(cashier);
        this.cashierLogIn();
    }
    get backBtnName() {
        return _t("Backend");
    }
    clickBack() {
        this.pos.closePos();
    }
}

registry.category("pos_pages").add("LoginScreen", {
    name: "LoginScreen",
    component: LoginScreen,
    route: `/pos/ui/${odoo.pos_config_id}/login`,
    params: {},
});
