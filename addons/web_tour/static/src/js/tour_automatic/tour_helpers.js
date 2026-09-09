/** @odoo-module native */
import { registry } from "@web/core/registry";

const tourHelperActions = registry.category("web_tour.helpers");

export class TourHelpers {
    constructor(anchor) {
        this.anchor = anchor;
        this.delay = 20;
        return new Proxy(this, {
            get(target, prop, receiver) {
                let value = Reflect.get(target, prop, receiver);
                if (value === undefined && typeof prop === "string") {
                    value = tourHelperActions.get(prop, undefined);
                }
                if (typeof value === "function" && prop !== "constructor") {
                    return value.bind(target);
                }
                return value;
            },
        });
    }
}
