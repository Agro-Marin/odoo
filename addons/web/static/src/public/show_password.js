// @ts-check
/** @odoo-module native */

/** @module @web/public/show_password - Interaction that toggles password field visibility via an eye icon button */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
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
            // the toggle is an icon-only button: without these it is an
            // unlabelled control whose state no assistive technology can read
            "t-att-aria-label": () =>
                this.showPassword ? _t("Hide password") : _t("Show password"),
            "t-att-aria-pressed": () => String(this.showPassword),
            // the markup carries a hardcoded, untranslated title; keep it in
            // step with the state and with the label
            "t-att-title": () =>
                this.showPassword ? _t("Hide password") : _t("Show password"),
        },
        // direct children only: the toggle owns its own group's control, and a
        // nested input-group's field is not its to reveal
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
