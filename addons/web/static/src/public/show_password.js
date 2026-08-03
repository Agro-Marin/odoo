// @ts-check
/** @odoo-module native */

/** @module @web/public/show_password */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

export class ShowPassword extends Interaction {
    static selector = ".input-group";
    static selectorHas = ":scope > .o_show_password";

    setup() {
        this.showPassword = false;
    }

    dynamicContent = {
        ".o_show_password": {
            "t-on-click": () => (this.showPassword = !this.showPassword),
            "t-att-aria-label": () =>
                this.showPassword ? _t("Hide password") : _t("Show password"),
            "t-att-aria-pressed": () => String(this.showPassword),
            "t-att-title": () =>
                this.showPassword ? _t("Hide password") : _t("Show password"),
        },
        ":scope > input[type='text'], :scope > input[type='password']": {
            "t-att-type": () => (this.showPassword ? "text" : "password"),
        },
        ".o_show_password > i": {
            "t-att-class": () => ({
                "fa-eye": !this.showPassword,
                "fa-eye-slash": !!this.showPassword,
            }),
        },
    };
}

registry.category("public.interactions").add("web.show_password", ShowPassword);
