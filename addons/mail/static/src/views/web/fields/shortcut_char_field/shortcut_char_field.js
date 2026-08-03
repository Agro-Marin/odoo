/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { CharField } from "@web/fields/basic/char/char_field";
export class ShortcutCharField extends Component {
    static template = "mail.ShortcutCharField";
    static components = { CharField };
    static props = { ...CharField.props };

    get charProps() {
        return {
            ...this.props,
            placeholder: _t("e.g. hello"),
        };
    }
}

registry.category("fields").add("shortcut", {
    component: ShortcutCharField,
});
