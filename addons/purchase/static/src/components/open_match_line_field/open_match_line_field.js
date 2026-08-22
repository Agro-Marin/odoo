/** @odoo-module native */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class OpenMatchLineField extends Component {
    static template = "purchase.OpenMatchLineField";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    async openMatchLine() {
        await this.action.doActionButton({
            type: "object",
            resId: this.props.record.resId,
            name: "action_open_line",
            resModel: "purchase.bill.line.match",
        });
    }
}

export const openMatchLineField = {
    component: OpenMatchLineField,
    displayName: _t("Open Matched Document"),
    supportedTypes: ["char"],
};

registerField("open_match_line", openMatchLineField);
