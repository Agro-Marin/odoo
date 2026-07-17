import { expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useService } from "@web/core/utils/hooks";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

// First unit coverage for the number buffer's numeric core (_updateBuffer):
// the service previously had no tests at all despite its edge-case surface.
const mountBufferHolder = async () => {
    class Dummy extends Component {
        static template = xml`<div/>`;
        static props = {};
        setup() {
            this.numberBuffer = useService("number_buffer");
            this.numberBuffer.use({});
        }
    }
    const comp = await mountWithCleanup(Dummy, { props: {} });
    return comp.numberBuffer;
};

test("digit entry, negation toggle and backspace", async () => {
    await setupPosEnv();
    const nb = await mountBufferHolder();
    nb._updateBuffer("1");
    nb._updateBuffer("2");
    expect(nb.get()).toBe("12");
    nb._updateBuffer("-");
    expect(nb.get()).toBe("-12");
    nb._updateBuffer("-");
    expect(nb.get()).toBe("12");
    nb._updateBuffer("+");
    expect(nb.get()).toBe("12");
    nb._updateBuffer("Backspace");
    expect(nb.get()).toBe("1");
});

test("negation as the first input yields -0", async () => {
    await setupPosEnv();
    const nb = await mountBufferHolder();
    nb._updateBuffer("-");
    expect(nb.get()).toBe("-0");
});

test("+N quick-cash keys add to the current value", async () => {
    await setupPosEnv();
    const nb = await mountBufferHolder();
    nb._updateBuffer("5");
    nb._updateBuffer("+10");
    expect(nb.getFloat()).toBe(15);
    nb._updateBuffer("+50");
    expect(nb.getFloat()).toBe(65);
});

test("the buffer stops growing past 12 digits", async () => {
    await setupPosEnv();
    const nb = await mountBufferHolder();
    for (let i = 0; i < 14; i++) {
        nb._updateBuffer("9");
    }
    expect(nb.get().length).toBeLessThan(14);
});
