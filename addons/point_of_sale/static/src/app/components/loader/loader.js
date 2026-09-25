/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLayoutEffect } from "@web/core/utils/layout_effect";

import { CriticalPOSError } from "./critical_pos_error/critical_pos_error.js";
const log = makeLogger("pos.boot.loader");

export class Loader extends Component {
    static template = "point_of_sale.Loader";
    static props = {
        loader: {
            type: Object,
            shape: { isShown: Boolean, error: [Object, Boolean, { value: null }] },
        },
    };
    static components = { CriticalPOSError };

    setup() {
        useLayoutEffect(
            (isShown) => {
                log.lifecycle("isShown", () => ({
                    isShown,
                    error: Boolean(this.props.loader.error),
                }));
                if (!isShown) {
                    setTimeout(() => {
                        this.__owl__.app.destroy();
                    }, 1000);
                }
            },
            () => [this.props.loader.isShown],
        );
    }
}
