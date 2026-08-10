/** @odoo-module native */
import { registry } from "@web/core/registry";

// Actions contributed by other addons. This class lives in the lazily-loaded
// ``web_tour.automatic`` child bundle, so an addon in another bundle that
// ``patch()``es this prototype patches a *different copy* of the class: its
// actions are silently never seen, and every step using one dies with
// ``TypeError: actionHelper[...] is not a function``. web_tour's own manifest
// documents the same trap for web_tour's own modules. ``@web/core/registry`` is
// a shared singleton across bundles, so registering is identity-safe from
// anywhere and needs no load-order coordination.
const tourHelperActions = registry.category("web_tour.helpers");

export class TourHelpers {
    constructor(anchor) {
        this.anchor = anchor;
        this.delay = 20;
        return new Proxy(this, {
            get(target, prop, receiver) {
                let value = Reflect.get(target, prop, receiver);
                // Resolved here rather than at the ``run:`` call site so a
                // registered action behaves exactly like a built-in one, whether
                // a step names it as a string (``run: "scan 123"``) or calls it
                // from a run function (``run(helpers) { helpers.scan("123") }``).
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
