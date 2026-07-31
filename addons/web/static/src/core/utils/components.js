// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/components */

import { Component, onError, xml } from "@odoo/owl";

export class ErrorHandler extends Component {
    static template = xml`<t t-slot="default" />`;
    static props = ["onError", "slots"];
    setup() {
        onError((/** @type {Error} */ error) => {
            this.props.onError(error);
        });
    }
}
