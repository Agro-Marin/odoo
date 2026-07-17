import { expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

const makeDeferred = () => {
    let resolve;
    const promise = new Promise((r) => (resolve = r));
    return { promise, resolve };
};

test("useTrackedAsync keepLast ignores a stale slow response", async () => {
    await setupPosEnv();

    class Dummy extends Component {
        static template = xml`<div/>`;
        static props = {};
        setup() {
            this.tracked = useTrackedAsync((deferred) => deferred.promise, {
                keepLast: true,
            });
        }
    }
    const comp = await mountWithCleanup(Dummy, { props: {} });

    const slow = makeDeferred();
    const fast = makeDeferred();
    comp.tracked.call(slow);
    comp.tracked.call(fast);

    fast.resolve("fast");
    await Promise.resolve();
    await Promise.resolve();
    expect(comp.tracked.status).toBe("success");
    expect(comp.tracked.result).toBe("fast");

    // The superseded first call settles late: its state writes must be
    // dropped — they used to overwrite the newer result ("keepLast" only
    // guarded the returned promise, not the reactive state).
    slow.resolve("slow");
    await Promise.resolve();
    await Promise.resolve();
    expect(comp.tracked.result).toBe("fast");
    expect(comp.tracked.status).toBe("success");
});
