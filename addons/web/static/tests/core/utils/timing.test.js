// @ts-check

import { describe, destroy, expect, getFixture, test } from "@odoo/hoot";
import { click, tick } from "@odoo/hoot-dom";
import {
    advanceTime,
    animationFrame,
    Deferred,
    microTick,
    runAllTimers,
} from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    batched,
    debounce,
    throttleForAnimation,
    useDebounced,
    useThrottleForAnimation,
} from "@web/core/utils/timing";

describe.current.tags("headless");

describe("batched", () => {
    test("a throwing callback is mirrored to console.error and still rejects", async () => {
        // Nearly all callers invoke the batched function fire-and-forget:
        // without the mirror, the error only surfaces as an
        // unhandledrejection whose stack points at the microtask.
        const errors = [];
        patchWithCleanup(console, {
            error: (...args) => errors.push(args),
        });
        const boom = new Error("boom");
        const fn = batched(() => {
            throw boom;
        });
        await expect(fn()).rejects.toThrow("boom");
        expect(errors).toHaveLength(1);
        expect(errors[0][0]).toBe(boom);
    });

    test("callback is called only once after operations", async () => {
        let n = 0;
        const fn = batched(() => n++);
        expect(n).toBe(0);

        fn();
        fn();
        expect(n).toBe(0);

        await microTick();
        expect(n).toBe(1);

        await microTick();
        expect(n).toBe(1);
    });

    test("callback is called only once after operations (synchronize at animationFrame)", async () => {
        let n = 0;
        const fn = batched(() => n++, animationFrame);
        expect(n).toBe(0);

        fn();
        fn();
        expect(n).toBe(0);

        await microTick();
        expect(n).toBe(0);

        await animationFrame();
        expect(n).toBe(1);

        await animationFrame();
        expect(n).toBe(1);
    });

    test("callback is called only once after operations (synchronize at setTimeout)", async () => {
        let n = 0;
        const fn = batched(() => n++, tick);
        expect(n).toBe(0);

        fn();
        fn();
        expect(n).toBe(0);

        await microTick();
        expect(n).toBe(0);

        await tick();
        expect(n).toBe(1);

        await tick();
        expect(n).toBe(1);
    });

    test("calling batched function from within the callback is not treated as part of the original batch", async () => {
        let n = 0;
        const fn = batched(() => ++n == 1 && fn());
        expect(n).toBe(0);

        fn();
        expect(n).toBe(0);

        await Promise.resolve(); // First batch
        expect(n).toBe(1);

        await Promise.resolve(); // Second batch initiated from within the callback
        expect(n).toBe(2);

        await Promise.resolve();
        expect(n).toBe(2);
    });

    test("calling batched function from within the callback is not treated as part of the original batch (synchronize at animationFrame)", async () => {
        let n = 0;
        const fn = batched(() => ++n == 1 && fn(), animationFrame);
        expect(n).toBe(0);

        fn();
        expect(n).toBe(0);

        await animationFrame(); // First batch
        expect(n).toBe(1);

        await animationFrame(); // Second batch initiated from within the callback
        expect(n).toBe(2);

        await animationFrame();
        expect(n).toBe(2);
    });

    test("calling batched function from within the callback is not treated as part of the original batch (synchronize at setTimeout)", async () => {
        let n = 0;
        const fn = batched(() => ++n === 1 && fn(), tick);
        expect(n).toBe(0);

        fn();
        expect(n).toBe(0);

        await tick(); // First batch
        expect(n).toBe(1);

        await tick(); // Second batch initiated from within the callback
        expect(n).toBe(2);

        await tick();
        expect(n).toBe(2);
    });

    test("callback is called twice", async () => {
        let n = 0;
        const fn = batched(() => n++);
        expect(n).toBe(0);

        fn();
        expect(n).toBe(0);

        await microTick();
        expect(n).toBe(1);

        fn();
        expect(n).toBe(1);

        await microTick();
        expect(n).toBe(2);
    });

    test("callback is called twice (synchronize at animationFrame)", async () => {
        let n = 0;
        const fn = batched(() => n++, animationFrame);

        expect(n).toBe(0);
        fn();

        expect(n).toBe(0);
        await animationFrame();
        expect(n).toBe(1);

        fn();
        expect(n).toBe(1);

        await animationFrame();
        expect(n).toBe(2);
    });

    test("callback is called twice (synchronize at setTimeout)", async () => {
        let n = 0;
        const fn = batched(() => n++, tick);
        expect(n).toBe(0);

        fn();
        expect(n).toBe(0);

        await tick();
        expect(n).toBe(1);

        fn();
        expect(n).toBe(1);

        await tick();
        expect(n).toBe(2);
    });
});

describe("debounce", () => {
    test("debounce on a sync function settles superseded calls too", async () => {
        const myFunc = () => {
            expect.step("myFunc");
            return 42;
        };
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc().then((x) => {
            expect.step("superseded " + x);
        });
        myDebouncedFunc().then((x) => {
            expect.step("resolved " + x);
        });
        expect.verifySteps([]);

        await advanceTime(3000);
        // func runs once (trailing edge), and BOTH the superseded call and the
        // last call resolve with its result (the superseded call used to hang).
        expect.verifySteps(["myFunc", "superseded 42", "resolved 42"]);
    });

    test("debounce on an async function settles superseded calls too", async () => {
        const imSearchDef = new Deferred();
        const myFunc = () => {
            expect.step("myFunc");
            return imSearchDef;
        };
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc().then((x) => {
            expect.step("superseded " + x);
        });
        myDebouncedFunc().then((x) => {
            expect.step("resolved " + x);
        });
        expect.verifySteps([]);

        await advanceTime(3000);
        expect.verifySteps(["myFunc"]);

        imSearchDef.resolve(42);
        await microTick(); // wait for promise returned by myFunc
        await microTick(); // wait for promise returned by debounce

        expect.verifySteps(["superseded 42", "resolved 42"]);
    });

    test("debounce propagates a rejection to every superseded call", async () => {
        const myFunc = () => {
            expect.step("myFunc");
            throw new Error("boom");
        };
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc().catch((e) => expect.step("rejected1 " + e.message));
        myDebouncedFunc().catch((e) => expect.step("rejected2 " + e.message));
        expect.verifySteps([]);

        await advanceTime(3000);
        expect.verifySteps(["myFunc", "rejected1 boom", "rejected2 boom"]);
    });

    test("debounce propagates an async rejection to every pending call", async () => {
        const imSearchDef = new Deferred();
        const myFunc = () => {
            expect.step("myFunc");
            return imSearchDef;
        };
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc().catch((e) => expect.step("rejected1 " + e));
        myDebouncedFunc().catch((e) => expect.step("rejected2 " + e));

        await advanceTime(3000);
        expect.verifySteps(["myFunc"]);

        imSearchDef.reject("nope");
        await microTick(); // wait for promise returned by myFunc
        await microTick(); // wait for promise returned by debounce
        expect.verifySteps(["rejected1 nope", "rejected2 nope"]);
    });

    test("cancel() releases a pending awaiter instead of hanging", async () => {
        const myFunc = () => expect.step("myFunc");
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc().then((v) => expect.step("settled " + v));
        myDebouncedFunc.cancel();
        await microTick();
        await microTick();
        // func is NOT executed, but the awaiter resolves (with undefined) so a
        // caller that awaits the debounced fn on teardown does not hang.
        expect.verifySteps(["settled undefined"]);
    });

    test("debounce with immediate", async () => {
        const myFunc = () => {
            expect.step("myFunc");
            return 42;
        };
        const myDebouncedFunc = debounce(myFunc, 3000, true);
        myDebouncedFunc().then((x) => {
            expect.step("resolved " + x);
        });
        expect.verifySteps(["myFunc"]);

        await microTick(); // wait for promise returned by myFunc
        await microTick(); // wait for promise returned by debounce

        expect.verifySteps(["resolved 42"]);

        myDebouncedFunc().then((x) => {
            expect.step("resolved " + x);
        });
        await runAllTimers();
        // func is NOT called (3000ms hasn't elapsed), but the suppressed call's
        // promise still resolves (undefined, like cancel()) when the cooldown
        // timer fires, so awaiters don't hang and entries don't accumulate.
        expect.verifySteps(["resolved undefined"]);

        myDebouncedFunc().then((x) => {
            expect.step("resolved " + x);
        });
        expect.verifySteps(["myFunc"]);

        await microTick(); // wait for promise returned by debounce
        await microTick(); // wait for promise returned chained onto it (step resolved x)
        expect.verifySteps(["resolved 42"]);
    });

    test("debounce with 'animationFrame' delay", async () => {
        const myFunc = () => expect.step("myFunc");

        debounce(myFunc, "animationFrame")();
        expect.verifySteps([]);
        await animationFrame();
        expect.verifySteps(["myFunc"]);
    });

    test("debounced call can be cancelled", async () => {
        const myFunc = () => {
            expect.step("myFunc");
        };
        const myDebouncedFunc = debounce(myFunc, 3000);
        myDebouncedFunc();
        myDebouncedFunc.cancel();
        await runAllTimers();
        expect.verifySteps([]); // Debounced call was cancelled

        myDebouncedFunc();
        await runAllTimers();
        expect.verifySteps(["myFunc"]); // Debounced call was not cancelled
    });

    test("debounce with leading and trailing", async () => {
        const myFunc = (lastValue) => {
            expect.step("myFunc");
            return lastValue;
        };
        const myDebouncedFunc = debounce(myFunc, 3000, {
            leading: true,
            trailing: true,
        });
        myDebouncedFunc(42).then((x) => expect.step("resolved " + x));
        myDebouncedFunc(43).then((x) => expect.step("resolved " + x));
        myDebouncedFunc(44).then((x) => expect.step("resolved " + x));
        expect.verifySteps(["myFunc"]);
        await microTick(); // wait for promise returned by debounce
        await microTick(); // wait for promise returned chained onto it (step resolved x)
        expect.verifySteps(["resolved 42"]);

        await runAllTimers();
        await microTick(); // wait for the inner promise
        // The trailing execution now settles every queued call (43 and 44), not
        // only the last one, so both resolve with the trailing result.
        expect.verifySteps(["myFunc", "resolved 44", "resolved 44"]);
    });
});

describe("throttleForAnimation", () => {
    test("single call is executed immediately", async () => {
        const throttledFn = throttleForAnimation((value) => {
            expect.step(`${value}`);
        });
        throttledFn(1);
        expect.verifySteps(["1"]);

        await runAllTimers();
        expect.verifySteps([]);
    });

    test("successive calls", async () => {
        const throttledFn = throttleForAnimation((value) => {
            expect.step(`${value}`);
        });
        throttledFn(1);
        expect.verifySteps(["1"]);

        throttledFn(2);
        throttledFn(3);
        expect.verifySteps([]);

        await runAllTimers();
        expect.verifySteps(["3"]);
    });

    test("successive calls (more precise timing)", async () => {
        const throttledFn = throttleForAnimation((value) => {
            expect.step(`${value}`);
        });
        throttledFn(1);
        expect.verifySteps(["1"]);

        await animationFrame();
        throttledFn(2);
        expect.verifySteps(["2"]);

        throttledFn(3);
        throttledFn(4);
        await animationFrame();
        expect.verifySteps(["4"]);

        await runAllTimers();
        expect.verifySteps([]);
    });

    test("can be cancelled", async () => {
        const throttledFn = throttleForAnimation((value) => {
            expect.step(`${value}`);
        });
        throttledFn(1);
        expect.verifySteps(["1"]);

        throttledFn(2);
        throttledFn(3);
        throttledFn.cancel();
        await runAllTimers();
        expect.verifySteps([]);
    });

    test("cancel() releases the pending trailing call's awaiter", async () => {
        const throttledFn = throttleForAnimation((value) => {
            expect.step(`${value}`);
            return value;
        });
        throttledFn(1);
        expect.verifySteps(["1"]);

        throttledFn(2).then((v) => expect.step(`settled ${v}`));
        throttledFn.cancel();
        await runAllTimers();
        // func is NOT executed for the cancelled trailing call, but its
        // promise settles (with undefined, same contract as debounce.cancel())
        // so a caller that awaits it — e.g. around unmount — does not hang.
        expect.verifySteps(["settled undefined"]);
    });
});

describe("throttleForAnimationScrollEvent", () => {
    test("scroll loses target", async () => {
        let throttled = new Deferred();
        const throttledFn = throttleForAnimation((val, targetEl) => {
            // In Chrome, scroll events' currentTarget is lost after the event
            // is handled (null here), so pass it explicitly if needed.
            const nodeName = val && val.currentTarget && val.currentTarget.nodeName;
            const targetName = targetEl && targetEl.nodeName;
            expect.step(
                `throttled function called with ${nodeName} in event, but ${targetName} in parameter`,
            );
            throttled.resolve();
        });

        const el = document.createElement("div");
        el.style = "position: absolute; overflow: scroll; height: 100px; width: 100px;";
        const childEl = document.createElement("div");
        childEl.style = "height: 200px; width: 200px;";
        let scrolled = new Deferred();
        el.appendChild(childEl);
        el.addEventListener("scroll", (ev) => {
            expect.step("before scroll");
            throttledFn(ev, ev.currentTarget);
            expect.step("after scroll");
            scrolled.resolve();
        });
        getFixture().appendChild(el);
        el.scrollBy(1, 1);
        el.scrollBy(2, 2);
        await scrolled;
        await throttled;

        expect.verifySteps([
            "before scroll",
            "throttled function called with DIV in event, but DIV in parameter",
            "after scroll",
        ]);

        throttled = new Deferred();
        scrolled = new Deferred();
        el.scrollBy(3, 3);
        await scrolled;
        expect.verifySteps([
            "before scroll",
            // Further call is delayed.
            "after scroll",
        ]);
        await throttled;
        expect.verifySteps([
            "throttled function called with null in event, but DIV in parameter",
        ]);
        el.remove();
    });
});

describe("useDebounced", () => {
    test("cancels on component destroy", async () => {
        class TestComponent extends Component {
            static template = xml`<button class="c" t-on-click="debounced">C</button>`;
            static props = ["*"];
            setup() {
                this.debounced = useDebounced(() => expect.step("debounced"), 1000);
            }
        }
        const component = await mountWithCleanup(TestComponent);
        expect.verifySteps([]);
        expect("button.c").toHaveCount(1);

        await click(`button.c`);
        await advanceTime(900);
        expect.verifySteps([]);

        await advanceTime(200);
        expect.verifySteps(["debounced"]);

        await click(`button.c`);
        await advanceTime(900);
        expect.verifySteps([]);

        destroy(component);
        await advanceTime(200);
        expect.verifySteps([]);
    });

    test("execBeforeUnmount option (callback not resolved before component destroy)", async () => {
        class TestComponent extends Component {
            static template = xml`<button class="c" t-on-click="() => this.debounced('hello')">C</button>`;
            static props = ["*"];
            setup() {
                this.debounced = useDebounced(
                    (p) => expect.step(`debounced: ${p}`),
                    1000,
                    {
                        execBeforeUnmount: true,
                    },
                );
            }
        }
        const component = await mountWithCleanup(TestComponent);
        expect.verifySteps([]);
        expect(`button.c`).toHaveCount(1);

        await click(`button.c`);
        await advanceTime(900);
        expect.verifySteps([]);

        await advanceTime(200);
        expect.verifySteps(["debounced: hello"]);

        await click(`button.c`);
        await advanceTime(900);
        expect.verifySteps([]);

        destroy(component);
        expect.verifySteps(["debounced: hello"]);
    });

    test("execBeforeUnmount option (callback resolved before component destroy)", async () => {
        class TestComponent extends Component {
            static template = xml`<button class="c" t-on-click="debounced">C</button>`;
            static props = ["*"];
            setup() {
                this.debounced = useDebounced(() => expect.step("debounced"), 1000, {
                    execBeforeUnmount: true,
                });
            }
        }
        const component = await mountWithCleanup(TestComponent);
        expect.verifySteps([]);
        expect(`button.c`).toHaveCount(1);

        await click(`button.c`);
        await advanceTime(900);
        expect.verifySteps([]);

        await advanceTime(200);
        expect.verifySteps(["debounced"]);

        destroy(component);
        await advanceTime(1000);
        expect.verifySteps([]);
    });
});

describe("useThrottleForAnimation", () => {
    test("cancels on component destroy", async () => {
        class TestComponent extends Component {
            static template = xml`<button class="c" t-on-click="throttled">C</button>`;
            static props = ["*"];
            setup() {
                this.throttled = useThrottleForAnimation(
                    () => expect.step("throttled"),
                    1000,
                );
            }
        }
        const component = await mountWithCleanup(TestComponent);
        expect.verifySteps([]);
        expect(`button.c`).toHaveCount(1);

        // Without destroy
        await click(`button.c`);
        expect.verifySteps(["throttled"]);

        await click(`button.c`);
        expect.verifySteps([]);

        await animationFrame();
        expect.verifySteps(["throttled"]);

        // Clean restart
        await runAllTimers();
        expect.verifySteps([]);

        // With destroy
        await click(`button.c`);
        expect.verifySteps(["throttled"]);

        await click(`button.c`);
        expect.verifySteps([]);

        destroy(component);
        await animationFrame();
        expect.verifySteps([]);
    });
});
