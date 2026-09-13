/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { standardFieldProps } from "@web/fields/standard_field_props";

const log = makeLogger("website.field.redirect_field");

class RedirectField extends Component {
    static template = "website.RedirectField";
    static props = { ...standardFieldProps };
    get info() {
        return this.props.record.data[this.props.name]
            ? _t("Published")
            : _t("Unpublished");
    }

    onClick() {
        log.logic("open_website_url", () => ({
            resModel: this.props.record.resModel,
            resId: this.props.record.resId,
        }));
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
