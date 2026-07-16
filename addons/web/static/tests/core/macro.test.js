// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import {
    advanceTime,
    animationFrame,
    click,
    edit,
    queryOne,
    queryText,
} from "@odoo/hoot-dom";
import { runAllTimers } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { Macro, waitUntil } from "@web/core/utils/macro";

let macro;
async function waitForMacro() {
    for (let i = 0; i < 50; i++) {
        await animationFrame();
        await advanceTime(265);
        if (macro.isComplete) {
            return;
        }
    }
    if (!macro.isComplete) {
        throw new Error(`Macro is not complete`);
    }
}

beforeEach(() => {
    patchWithCleanup(Macro.prototype, {
        start() {
            super.start(...arguments);
            macro = this;
        },
    });
});

class TestComponent extends Component {
    static template = xml`
        <div class="counter">
            <p><button class="btn inc" t-on-click="() => this.state.value++">increment</button></p>
            <p><button class="btn dec" t-on-click="() => this.state.value--">decrement</button></p>
            <p><button class="btn double" t-on-click="() => this.state.value = 2*this.state.value">double</button></p>
            <span class="value"><t t-esc="state.value"/></span>
            <input />
        </div>`;
    static props = ["*"];
    setup() {
        this.state = useState({ value: 0 });
    }
}

test("simple use", async () => {
    await mountWithCleanup(TestComponent);
    new Macro({
        name: "test",
        steps: [
            {
                trigger: "button.inc",
                async action(trigger) {
                    await click(trigger);
                },
            },
        ],
        async onStep({ trigger }) {
            await animationFrame();
            expect.step(queryText("span.value"));
        },
    }).start(queryOne(".counter"));

    const span = queryOne("span.value");
    expect(span).toHaveText("0");
    await waitForMacro();
    expect.verifySteps(["1"]);
});

test("multiple steps", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    expect(span).toHaveText("0");

    new Macro({
        name: "test",
        steps: [
            {
                trigger: "button.inc",
                async action(trigger) {
                    await click(trigger);
                },
            },
            {
                trigger: () => (span.textContent === "1" ? span : null),
            },
            {
                trigger: "button.inc",
                async action(trigger) {
                    await click(trigger);
                },
            },
        ],
        async onStep({ index }) {
            await animationFrame();
            if (index % 2 === 0) {
                expect.step(queryText("span.value"));
            }
        },
    }).start(queryOne(".counter"));
    await waitForMacro();
    expect.verifySteps(["1", "2"]);
});

test("can input values", async () => {
    await mountWithCleanup(TestComponent);
    const input = queryOne("input");
    new Macro({
        name: "test",
        steps: [
            {
                trigger: "div.counter input",
                async action(trigger) {
                    await click(trigger);
                    await edit("aaron", { confirm: "blur" });
                },
            },
        ],
    }).start(queryOne(".counter"));
    expect(input).toHaveValue("");
    await waitForMacro();
    expect(input).toHaveValue("aaron");
});

test("a step can have no trigger", async () => {
    await mountWithCleanup(TestComponent);
    const input = queryOne("input");
    new Macro({
        name: "test",
        steps: [
            { action: () => expect.step("1") },
            { action: () => expect.step("2") },
            {
                trigger: "div.counter input",
                async action(trigger) {
                    await click(trigger);
                    await edit("aaron", { confirm: "blur" });
                },
            },
            { action: () => expect.step("3") },
        ],
    }).start(queryOne(".counter"));
    expect(input).toHaveValue("");
    await waitForMacro();
    expect(input).toHaveValue("aaron");
    expect.verifySteps(["1", "2", "3"]);
});

test("onStep function is called at each step", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    expect(span).toHaveText("0");

    new Macro({
        name: "test",
        onStep: ({ index }) => {
            expect.step(index);
        },
        steps: [
            {
                action: () => {
                    console.log("brol");
                },
            },
            {
                trigger: "button.inc",
                async action(trigger) {
                    await click(trigger);
                },
            },
        ],
    }).start(queryOne(".counter"));
    await waitForMacro();
    expect(span).toHaveText("1");
    expect.verifySteps([0, 1]);
});

test("trigger can be a function returning an htmlelement", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    expect(span).toHaveText("0");

    new Macro({
        name: "test",
        steps: [
            {
                trigger: () => queryOne("button.inc"),
                async action(trigger) {
                    await click(trigger);
                },
            },
        ],
    }).start(queryOne(".counter"));
    expect(span).toHaveText("0");
    await waitForMacro();
    expect(span).toHaveText("1");
});

test("macro wait element is visible to do action", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    const button = queryOne("button.inc");
    button.classList.add("d-none");
    expect(span).toHaveText("0");
    new Macro({
        name: "test",
        timeout: 1000,
        steps: [
            {
                trigger: "button.inc",
                action: () => {
                    expect.step("element is now visible");
                },
            },
        ],
        onError: (error) => {
            expect.step(error);
        },
    }).start(queryOne(".counter"));
    advanceTime(500);
    button.classList.remove("d-none");
    await waitForMacro();
    expect.verifySteps(["element is now visible"]);
});

test("macro timeout if element is not visible", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    const button = queryOne("button.inc");
    button.classList.add("d-none");
    expect(span).toHaveText("0");
    const macro = new Macro({
        name: "test",
        timeout: 1000,
        steps: [
            {
                trigger: "button.inc",
                action: () => {
                    expect.step("element is now visible");
                },
            },
        ],
        onError: ({ error }) => {
            expect.step(error.message);
        },
    });
    macro.start(queryOne(".counter"));
    await waitForMacro();
    expect.verifySteps(["TIMEOUT step failed to complete within 1000 ms."]);
});

test("macro without onError falls back to a console.error default", async () => {
    // The handlers must not be class fields: an own no-op field would make
    // this default (and any subclass prototype handler) dead code.
    patchWithCleanup(console, {
        error: (message, step, index) => expect.step(`${message} @${index}`),
    });
    new Macro({
        name: "test",
        timeout: 1000,
        steps: [{ trigger: ".does-not-exist" }],
    }).start();
    await waitForMacro();
    expect.verifySteps(["TIMEOUT step failed to complete within 1000 ms. @0"]);
});

test("subclass prototype onError receives { error, step, index }", async () => {
    class SubMacro extends Macro {
        onError({ error, step, index }) {
            expect.step(`${error.message} @${index} trigger:${step.trigger}`);
        }
    }
    new SubMacro({
        name: "test",
        timeout: 1000,
        steps: [{ trigger: ".does-not-exist" }],
    }).start();
    await waitForMacro();
    expect.verifySteps([
        "TIMEOUT step failed to complete within 1000 ms. @0 trigger:.does-not-exist",
    ]);
});

test("descriptor onError wins over the default and a subclass prototype onError", async () => {
    patchWithCleanup(console, {
        error: () => expect.step("console.error (default onError)"),
    });
    class SubMacro extends Macro {
        onError() {
            expect.step("prototype onError");
        }
    }
    new SubMacro({
        name: "test",
        timeout: 1000,
        steps: [{ trigger: ".does-not-exist" }],
        onError: ({ error }) => expect.step(`descriptor onError: ${error.message}`),
    }).start();
    await waitForMacro();
    expect.verifySteps([
        "descriptor onError: TIMEOUT step failed to complete within 1000 ms.",
    ]);
});

test("macro clears the step timeout timer once the step settles", async () => {
    // Every step used to leave its (up to 10s) timeout running after
    // winning the race — pure waste that made timing-sensitive tests flakier
    // under fake timers. `browser.setTimeout`/`clearTimeout` are made
    // non-configurable by the test harness (so the timer calls can't be spied
    // on directly). Instead we watch the step's own AbortController: a timeout
    // timer that outlives its settled step fires later and aborts that (already
    // finished) controller a second time. With the fix, the timer is cleared,
    // so firing every remaining timer triggers no further abort.
    await mountWithCleanup(TestComponent);
    let stepControllerAborts = 0;
    patchWithCleanup(AbortController.prototype, {
        abort() {
            // `macro` is captured by the `Macro.prototype.start` patch above;
            // `macro.abortController` is the (single) step's controller.
            if (macro && this === macro.abortController) {
                stepControllerAborts++;
            }
            return super.abort(...arguments);
        },
    });
    new Macro({
        name: "test",
        timeout: 1234,
        steps: [
            {
                trigger: "button.inc",
                action: (el) => el.click(),
            },
        ],
    }).start(queryOne(".counter"));
    await waitForMacro();
    expect(queryOne("span.value")).toHaveText("1");
    // The macro aborts its step controller exactly once, on completion.
    expect(stepControllerAborts).toBe(1);
    // Fire every remaining timer: a leftover timeout timer would abort the
    // step controller again here. The fix cleared it, so the count is stable.
    await runAllTimers();
    expect(stepControllerAborts).toBe(1);
});

test("a string action fails fast at construction", async () => {
    // `action` is always CALLED, so a string action can never work; the schema
    // must reject it up front instead of letting it die at runtime.
    expect(
        () =>
            new Macro({
                name: "test",
                steps: [{ action: "doStuff" }],
            }),
    ).toThrow(/Error in schema for Macro/);
});

test("Macro.STOP halts the macro without onComplete or onError", async () => {
    await mountWithCleanup(TestComponent);
    const span = queryOne("span.value");
    expect(span).toHaveText("0");
    new Macro({
        name: "test",
        steps: [
            // Returning the sentinel halts the macro before the next step.
            { action: () => Macro.STOP },
            {
                trigger: "button.inc",
                async action(trigger) {
                    await click(trigger);
                },
            },
        ],
        onComplete: () => expect.step("onComplete"),
        onError: () => expect.step("onError"),
    }).start(queryOne(".counter"));
    await waitForMacro();
    // The second step never ran and no completion/error callback fired.
    expect(span).toHaveText("0");
    expect.verifySteps([]);
});

test("waitUntil rejects when the predicate throws inside the rAF loop", async () => {
    let n = 0;
    const prom = waitUntil(() => {
        n++;
        if (n >= 2) {
            throw new Error("predicate boom");
        }
        return false;
    });
    let caught;
    const settled = prom.catch((error) => (caught = error));
    await runAllTimers();
    await settled;
    expect(caught).toBeInstanceOf(Error);
    expect(caught.message).toBe("predicate boom");
});
