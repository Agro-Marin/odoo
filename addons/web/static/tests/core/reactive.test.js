// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus, reactive } from "@odoo/owl";
import { derived, effect, SignalStore } from "@web/core/utils/reactive";

describe.current.tags("headless");

describe("class", () => {
    test("callback registered without SignalStore class constructor will not notify", async () => {
        const bus = new EventBus();
        class MyReactiveClass {
            constructor() {
                this.counter = 0;
                bus.addEventListener("change", () => this.counter++);
            }
        }

        const obj = reactive(new MyReactiveClass(), () => {
            expect.step(`counter: ${obj.counter}`);
        });

        obj.counter;
        obj.counter++;
        expect.verifySteps(["counter: 1"]);
        bus.trigger("change");
        expect(obj.counter).toBe(2);
        expect.verifySteps([]);
    });

    test("callback registered in SignalStore class constructor will notify", async () => {
        const bus = new EventBus();
        class MyReactiveClass extends SignalStore {
            constructor() {
                super();
                this.counter = 0;
                bus.addEventListener("change", () => this.counter++);
            }
        }
        const obj = reactive(new MyReactiveClass(), () => {
            expect.step(`counter: ${obj.counter}`);
        });
        obj.counter;
        obj.counter++;
        expect.verifySteps(["counter: 1"]);
        bus.trigger("change");
        expect(obj.counter).toBe(2);
        expect.verifySteps(["counter: 2"]);
    });
});

describe("effect", () => {
    test("effect runs once immediately", async () => {
        const state = reactive({ counter: 0 });
        expect.verifySteps([]);
        effect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );
        expect.verifySteps(["counter: 0"]);
    });

    test("effect runs when reactive deps change", async () => {
        const state = reactive({ counter: 0 });
        expect.verifySteps([]);
        effect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );
        expect.verifySteps(["counter: 0"]);

        state.counter++;
        expect.verifySteps(["counter: 1"]);

        state.counter++;
        expect.verifySteps(["counter: 2"]);
    });

    test("Original reactive callback is not subscribed to keys observed by effect", async () => {
        let reactiveCallCount = 0;
        const state = reactive(
            {
                counter: 0,
            },
            () => reactiveCallCount++,
        );
        expect.verifySteps([]);
        expect(reactiveCallCount).toBe(0);
        effect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );
        expect.verifySteps(["counter: 0"]);
        expect(reactiveCallCount).toBe(0, {
            message: "did not call the original reactive's callback",
        });
        state.counter = 1;
        expect.verifySteps(["counter: 1"]);
        expect(reactiveCallCount).toBe(0, {
            message: "did not call the original reactive's callback",
        });
        state.counter;
        state.counter = 2;
        expect.verifySteps(["counter: 2"]);
        expect(reactiveCallCount).toBe(1, {
            message:
                "the original callback was called because it is subscribed independently",
        });
    });

    test("mutating keys not observed by the effect doesn't cause it to run", async () => {
        const state = reactive({ counter: 0, unobserved: 0 });
        effect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );

        expect.verifySteps(["counter: 0"]);
        state.counter = 1;
        expect.verifySteps(["counter: 1"]);
        state.unobserved = 1;
        expect.verifySteps([]);
    });
});

describe("derived", () => {
    test("reads its computation through .value", () => {
        const d = derived(() => 6 * 7);
        expect(d.value).toBe(42);
    });

    test("is lazy: the computation does not run until .value is read", () => {
        let calls = 0;
        const d = derived(() => {
            calls++;
            return "x";
        });
        expect(calls).toBe(0);
        d.value;
        expect(calls).toBe(1);
    });

    test("is not memoized: every read re-runs the computation", () => {
        let calls = 0;
        const d = derived(() => ++calls);
        expect(d.value).toBe(1);
        expect(d.value).toBe(2);
        expect(calls).toBe(2);
    });

    test("always reflects the current value of its sources", () => {
        const state = reactive({ x: 1 });
        const d = derived(() => state.x);
        expect(d.value).toBe(1);
        state.x = 9;
        expect(d.value).toBe(9);
    });

    test("read inside an effect, it subscribes the effect to its sources", () => {
        // The whole point of the free-standing form: `.value`'s reads are
        // tracked by whatever reactive scope reads it, so mutating a source
        // re-runs that scope -- no explicit computed node, just OWL's Proxy.
        const state = reactive({ a: 1, b: 2 });
        effect(
            (observed) => {
                const total = derived(() => observed.a + observed.b);
                expect.step(`total: ${total.value}`);
            },
            [state],
        );
        expect.verifySteps(["total: 3"]);
        state.a = 10;
        expect.verifySteps(["total: 12"]);
        state.b = 100;
        expect.verifySteps(["total: 110"]);
    });
});
