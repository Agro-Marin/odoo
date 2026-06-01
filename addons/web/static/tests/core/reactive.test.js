// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus, reactive } from "@odoo/owl";
import { derived, effect, memoizedDerived, SignalStore } from "@web/core/utils/reactive";

describe.current.tags("headless");

describe("class", () => {
    test("callback registered without SignalStore class constructor will not notify", async () => {
        // This test exists to showcase why we need the SignalStore class
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

        obj.counter; // initial subscription to counter
        obj.counter++;
        expect.verifySteps(["counter: 1"]);
        bus.trigger("change");
        expect(obj.counter).toBe(2);
        expect.verifySteps([
            // The mutation in the event handler was missed by the reactivity, this is because
            // the `this` in the event handler is captured during construction and is not reactive
        ]);
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
        obj.counter; // initial subscription to counter
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
        // effect runs immediately
        expect.verifySteps(["counter: 0"]);

        state.counter++;
        // first mutation runs the effect
        expect.verifySteps(["counter: 1"]);

        state.counter++;
        // subsequent mutations run the effect
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
        state.counter; // subscribe the original reactive
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

describe("memoizedDerived", () => {
    test("evaluates lazily and caches across reads with no mutation", async () => {
        const state = reactive({ a: 1, b: 2, c: 3 });
        let calls = 0;
        const sum = memoizedDerived(
            (s) => {
                calls++;
                return s.a + s.b + s.c;
            },
            [state],
        );
        // No evaluation before .value is read.
        expect(calls).toBe(0);
        expect(sum.value).toBe(6);
        expect(sum.value).toBe(6);
        expect(sum.value).toBe(6);
        expect(calls).toBe(1, {
            message: "fn ran once for three reads with no mutation",
        });
    });

    test("re-evaluates after a tracked dep mutates", async () => {
        const state = reactive({ a: 10, b: 20 });
        let calls = 0;
        const product = memoizedDerived(
            (s) => {
                calls++;
                return s.a * s.b;
            },
            [state],
        );
        expect(product.value).toBe(200);
        expect(product.value).toBe(200);
        expect(calls).toBe(1);
        state.a = 5;
        expect(product.value).toBe(100);
        expect(calls).toBe(2);
        state.b = 7;
        expect(product.value).toBe(35);
        expect(calls).toBe(3);
    });

    test("untracked mutations do not invalidate", async () => {
        const tracked = reactive({ x: 1 });
        const untracked = reactive({ y: 100 });
        let calls = 0;
        const m = memoizedDerived(
            (s) => {
                calls++;
                return s.x;
            },
            [tracked],
        );
        expect(m.value).toBe(1);
        expect(calls).toBe(1);
        untracked.y = 999;
        expect(m.value).toBe(1);
        expect(calls).toBe(1, {
            message: "mutation on object outside deps did not invalidate",
        });
    });

    test("re-subscription survives across many mutate-read cycles", async () => {
        const state = reactive({ n: 0 });
        let calls = 0;
        const doubled = memoizedDerived(
            (s) => {
                calls++;
                return s.n * 2;
            },
            [state],
        );
        expect(doubled.value).toBe(0); // initial eval
        for (let i = 1; i <= 5; i++) {
            state.n = i;
            expect(doubled.value).toBe(i * 2); // re-eval after each mutation
            expect(doubled.value).toBe(i * 2); // second read cached
        }
        expect(calls).toBe(6, {
            message: "1 initial eval + 5 mutation-triggered re-evals",
        });
    });

    test("only properties read on the latest evaluation are tracked", async () => {
        const state = reactive({ a: 1, b: 2, useA: true });
        let calls = 0;
        const branch = memoizedDerived(
            (s) => {
                calls++;
                return s.useA ? s.a : s.b;
            },
            [state],
        );
        // First read takes the useA-true branch: tracks useA and a.
        expect(branch.value).toBe(1);
        expect(calls).toBe(1);
        // b was not read on this branch — mutating it must not invalidate.
        state.b = 99;
        expect(branch.value).toBe(1);
        expect(calls).toBe(1);
        // useA was read — flipping it invalidates.
        state.useA = false;
        expect(branch.value).toBe(99);
        expect(calls).toBe(2);
        // Now we are on the useA-false branch: tracks useA and b. Mutating a
        // (which is no longer read) must not invalidate.
        state.a = 999;
        expect(branch.value).toBe(99);
        expect(calls).toBe(2);
    });

    test("same-value writes do not invalidate", async () => {
        const state = reactive({ n: 5 });
        let calls = 0;
        const m = memoizedDerived(
            (s) => {
                calls++;
                return s.n;
            },
            [state],
        );
        expect(m.value).toBe(5);
        expect(calls).toBe(1);
        state.n = 5; // OWL's set trap short-circuits same-value writes
        expect(m.value).toBe(5);
        expect(calls).toBe(1);
    });

    test("nested reactive reads invalidate the parent memoization", async () => {
        const state = reactive({ inner: { name: "alice", age: 30 } });
        let calls = 0;
        const label = memoizedDerived(
            (s) => {
                calls++;
                return `${s.inner.name}-${s.inner.age}`;
            },
            [state],
        );
        expect(label.value).toBe("alice-30");
        expect(label.value).toBe("alice-30");
        expect(calls).toBe(1);
        state.inner.age = 31;
        expect(label.value).toBe("alice-31");
        expect(calls).toBe(2);
    });

    test("multiple deps are all tracked", async () => {
        const a = reactive({ x: 1 });
        const b = reactive({ y: 10 });
        let calls = 0;
        const sum = memoizedDerived(
            (ra, rb) => {
                calls++;
                return ra.x + rb.y;
            },
            [a, b],
        );
        expect(sum.value).toBe(11);
        a.x = 5;
        expect(sum.value).toBe(15);
        b.y = 100;
        expect(sum.value).toBe(105);
        expect(calls).toBe(3);
    });

    test("array deps: push/pop are tracked", async () => {
        const arr = reactive([1, 2, 3]);
        let calls = 0;
        const total = memoizedDerived(
            (a) => {
                calls++;
                return a.reduce((s, x) => s + x, 0);
            },
            [arr],
        );
        expect(total.value).toBe(6);
        arr.push(4);
        expect(total.value).toBe(10);
        arr.pop();
        expect(total.value).toBe(6);
        expect(calls).toBe(3);
    });
});

describe("derived", () => {
    test("reads through .value evaluate the thunk each time (no memoization)", async () => {
        // Distinct from memoizedDerived which caches across reads.
        // ``derived`` exists purely to give derived state a grep-able
        // name; the thunk runs every read so the doc can claim "no
        // memoization, OWL's scheduler already batches renders".
        const state = reactive({ a: 1, b: 2 });
        let calls = 0;
        const sum = derived(() => {
            calls++;
            return state.a + state.b;
        });
        expect(calls).toBe(0); // lazy until first read
        expect(sum.value).toBe(3);
        expect(sum.value).toBe(3);
        expect(sum.value).toBe(3);
        expect(calls).toBe(3, {
            message: "thunk runs once per .value read — no caching",
        });
    });

    test("returns current value after mutation", async () => {
        const state = reactive({ price: 100, qty: 2 });
        const total = derived(() => state.price * state.qty);
        expect(total.value).toBe(200);
        state.qty = 5;
        expect(total.value).toBe(500);
        state.price = 10;
        expect(total.value).toBe(50);
    });

    test("does not auto-subscribe a standalone observer to the thunk's reads", async () => {
        // OWL binds a reactive's callback at proxy-creation time and exposes no
        // execution-context hook to attribute a thunk's reads to an arbitrary
        // observer (see the ``memoizedDerived`` docstring). So a standalone
        // ``reactive(squared, cb)`` observer is subscribed to ``squared.value``,
        // not to ``state.n`` read inside the thunk: mutating ``state`` does NOT
        // fire ``cb``. Auto-tracking only happens when the thunk reads reactives
        // already bound to the observer's callback (e.g. a component render
        // reading its own useState/props). A direct read still recomputes.
        const state = reactive({ n: 1 });
        const squared = derived(() => state.n * state.n);
        let observed;
        const cb = () => {
            observed = squared.value;
        };
        const tracker = reactive(squared, cb);
        tracker.value; // subscribes cb to squared.value, not to state.n
        state.n = 3;
        expect(observed).toBe(undefined); // cb does not fire: no auto-tracking
        expect(squared.value).toBe(9); // but a direct read recomputes correctly
        state.n = 4;
        expect(squared.value).toBe(16);
    });

    test("composes with another derived", async () => {
        const state = reactive({ x: 2, y: 3 });
        const sum = derived(() => state.x + state.y);
        const doubled = derived(() => sum.value * 2);
        expect(doubled.value).toBe(10);
        state.x = 5;
        expect(doubled.value).toBe(16);
    });

    test("recomputes the branch taken at read time", async () => {
        // derived recomputes on every read, so it always reflects the branch
        // taken at read time and only the values on that path. (Maintaining
        // subscriptions / branch-pruned observer invalidation is
        // ``memoizedDerived``'s concern, covered by its own branch-dep tests —
        // ``derived`` itself never subscribes a standalone observer; see the
        // test above.)
        const state = reactive({ useA: true, a: 1, b: 100 });
        const picked = derived(() => (state.useA ? state.a : state.b));
        expect(picked.value).toBe(1);
        state.b = 999; // off the current branch
        expect(picked.value).toBe(1);
        state.a = 42;
        expect(picked.value).toBe(42);
        state.useA = false; // switch branch
        expect(picked.value).toBe(999);
    });
});

