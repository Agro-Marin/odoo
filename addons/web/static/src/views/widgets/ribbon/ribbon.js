// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/ribbon/ribbon */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class RibbonWidget extends Component {
    static template = "web.Ribbon";
    static props = {
        ...standardWidgetProps,
        record: { type: Object, optional: true },
        text: { type: String },
        title: { type: String, optional: true },
        bgClass: { type: String, optional: true },
    };
    static defaultProps = {
        title: "",
        bgClass: "text-bg-success",
    };

    /** @returns {string} */
    get classes() {
        let classes = this.props.bgClass;
        if (this.props.text.length > 15) {
            classes += " o_small";
        } else if (this.props.text.length > 10) {
            classes += " o_medium";
        }
        return classes;
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const ribbonWidget = {
    component: RibbonWidget,
    extractProps: ({ attrs }) => ({
        text: attrs.title || attrs.text || "",
        title: attrs.tooltip,
        bgClass: attrs.bg_color,
    }),
    supportedAttributes: [
        {
            label: _t("Title"),
            name: "title",
            type: "string",
        },
        {
            label: _t("Background color"),
            name: "bg_color",
            type: "string",
        },
        {
            label: _t("Tooltip"),
            name: "tooltip",
            type: "string",
        },
    ],
};

registry.category("view_widgets").add("web_ribbon", ribbonWidget);
