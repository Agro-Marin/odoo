/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets";

export class ColorsResetButton extends Component {
    static template = `im_livechat.ColorsResetButton`;
    static props = {
        ...standardWidgetProps,
        default_colors: { type: Object },
    };

    onColorsResetButtonClick() {
        this.props.record.update(this.props.default_colors);
    }
}

export const colorsResetButton = {
    component: ColorsResetButton,
    extractProps: ({ options }) => ({
        default_colors: options.default_colors,
    }),
};
registry.category("view_widgets").add("colors_reset_button", colorsResetButton);
