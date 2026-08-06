// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus, reactive } from "@odoo/owl";
import { disposableEffect, effect, SignalStore } from "@web/core/utils/reactive";

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

    test("effect returns a disposer that stops future notifications", async () => {
        const state = reactive({ counter: 0 });
        const dispose = effect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );
        expect(dispose).toBeInstanceOf(Function);
        expect.verifySteps(["counter: 0"]);

        state.counter++;
        expect.verifySteps(["counter: 1"]);

        dispose();
        state.counter++;
        expect.verifySteps([]);
    });

    test("disposableEffect still runs, notifies and disposes", async () => {
        const state = reactive({ counter: 0 });
        const dispose = disposableEffect(
            (state) => {
                expect.step(`counter: ${state.counter}`);
            },
            [state],
        );
        expect.verifySteps(["counter: 0"]);

        state.counter++;
        expect.verifySteps(["counter: 1"]);

        dispose();
        state.counter++;
        expect.verifySteps([]);
    });
});
