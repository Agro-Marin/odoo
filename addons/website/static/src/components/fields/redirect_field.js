/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { standardFieldProps } from "@web/fields/standard_field_props";

class RedirectField extends Component {
    static template = "website.RedirectField";
    static props = { ...standardFieldProps };
    get info() {
        return this.props.record.data[this.props.name]
            ? _t("Published")
            : _t("Unpublished");
    }

    onClick() {
        this.env.onClickViewButton({
            clickParams: {
                type: "object",
                name: "open_website_url",
            },
            getResParams: () =>
                pick(
                    this.props.record,
                    "context",
                    "evalContext",
                    "resModel",
                    "resId",
                    "resIds",
                ),
        });
    }
}

registry.category("fields").add("website_redirect_button", {
    component: RedirectField,
});
