// @ts-check

import "@web/webclient/debug/profiling/profiling_service";

import { describe, expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";

describe.current.tags("headless");

/** @returns {any} */
function debugItemFactory() {
    return registry.category("debug").category("default").get("profilingItem");
}

/** @param {string} tag */
function fakeProfilingService(tag) {
    return {
        profilingItem: () => ({ type: "component", tag }),
    };
}

describe("the profiling debug item is registered once, resolved per env", () => {
    test("it is registered at module scope, not per service construction", () => {
        expect(typeof debugItemFactory()).toBe("function", {
            message:
                "the entry must exist without any ProfilingService having been " +
                "constructed; it used to be added from the constructor",
        });
    });

    test("it resolves against the env it is asked about", () => {
        const factory = debugItemFactory();
        const first = factory({
            env: { services: { profiling: fakeProfilingService("first") } },
        });
        const second = factory({
            env: { services: { profiling: fakeProfilingService("second") } },
        });

        expect(first.tag).toBe("first");
        expect(second.tag).toBe("second");
    });

    test("it yields nothing when the service did not start", () => {
        expect(debugItemFactory()({ env: { services: {} } })).toBe(null);
    });
});
