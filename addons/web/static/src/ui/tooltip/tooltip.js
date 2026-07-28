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
        /**
         * Id the tooltipped element points at with `aria-describedby`. Without
         * it the tooltip is an unreferenced `<div>`: the service removes the
         * element's `title` while a custom tooltip is up (so the native one
         * does not show alongside), which would otherwise leave assistive tech
         * with strictly less than it had before the hover.
         */
        id: { type: String, optional: true },
    };
}
