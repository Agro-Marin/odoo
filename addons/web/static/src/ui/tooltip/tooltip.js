// @ts-check
/** @odoo-module native */

/** @module @web/ui/tooltip/tooltip - Simple tooltip component rendered by the tooltip service */

import { Component } from "@odoo/owl";

export class Tooltip extends Component {
    static template = "web.Tooltip";
    static props = {
        close: Function,
        tooltip: { type: String, optional: true },
        template: { type: String, optional: true },
        info: { optional: true },
    };
}
