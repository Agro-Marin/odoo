// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, markup, onWillStart, xml } from "@odoo/owl";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { Interaction } from "@web/public/interaction";

import { startInteraction } from "./helpers.js";

describe.current.tags("interaction_dev");

test("properly fallback to body when we have no match for wrapwrap", async () => {
    const env = await makeMockEnv();
    expect(env.services["public.interactions"].el).toBe(document.querySelector("body"));
});

test("wait for translation before starting interactions", async () => {
    class Test extends Interaction {
        static selector = ".test";

        setup() {
            expect("localization" in this.services).toBe(true);
        }
    }
    await startInteraction(Test, `<div class="test"></div>`);
});

test("starting interactions twice should only actually do it once", async () => {
    let n = 0;
    class Test extends Interaction {
        static selector = ".test";

        setup() {
            n++;
        }
    }

    const { core } = await startInteraction(Test, `<div class="test"></div>`);

    expect(n).toBe(1);
    core.startInteractions();
    await animationFrame();
    expect(n).toBe(1);
});

test("start interactions even if there is a crash", async () => {
    expect.errors(1);
    class Boom extends Interaction {
        static selector = ".test";

        setup() {
            expect.step("start boom");
            throw new Error("boom");
        }
        destroy() {
            expect.step("destroy boom");
        }
    }
    class NotBoom extends Interaction {
        static selector = ".test";

        setup() {
            expect.step("start notboom");
        }
        destroy() {
            expect.step("destroy notboom");
        }
    }

    const { core } = await startInteraction(
        [Boom, NotBoom],
        `<div class="test"></div>`,
        {
            waitForStart: false,
        },
    );
    await expect(core.isReady).rejects.toThrow("boom");
    expect.verifySteps(["start boom", "start notboom"]);
    core.stopInteractions();
    expect.verifySteps(["destroy notboom"]);
    await animationFrame();
    expect.verifyErrors([/boom/]);
});

test("start interactions even if there is a crash when evaluating selector", async () => {
    expect.errors(1);
    class Boom extends Interaction {
        static selector = "div:invalid(coucou)";

        setup() {
            expect.step("start boom");
        }
        destroy() {
            expect.step("destroy boom");
        }
    }
    class NotBoom extends Interaction {
        static selector = ".test";

        setup() {
            expect.step("start notboom");
        }
    }

    const { core } = await startInteraction(
        [Boom, NotBoom],
        `<div class="test"></div>`,
        {
            waitForStart: false,
        },
    );

    await expect(core.isReady).rejects.toThrow(
        "Could not start interaction Boom (invalid selector: 'div:invalid(coucou)')",
    );
    expect.verifySteps(["start notboom"]);
    await animationFrame();
    expect.verifyErrors([/invalid selector: 'div:invalid\(coucou\)'/]);
});

test("start interactions even if there is a crash when evaluating selectorHas", async () => {
    expect.errors(1);
    class Boom extends Interaction {
        static selector = ".test";
        static selectorHas = "div:invalid(coucou)";

        setup() {
            expect.step("start boom");
        }
        destroy() {
            expect.step("destroy boom");
        }
    }
    class NotBoom extends Interaction {
        static selector = ".test";

        setup() {
            expect.step("start notboom");
        }
    }

    const { core } = await startInteraction(
        [Boom, NotBoom],
        `<div class="test"><div></div></div>`,
        {
            waitForStart: false,
        },
    );

    await expect(core.isReady).rejects.toThrow(
        "Could not start interaction Boom (invalid selector: '.test' or selectorHas: 'div:invalid(coucou)')",
    );
    expect.verifySteps(["start notboom"]);
    await animationFrame();
    expect.verifyErrors([/selectorHas: 'div:invalid\(coucou\)'/]);
});

test("start interactions with selectorHas", async () => {
    class Test extends Interaction {
        static selector = ".test";
        static selectorHas = ".inner";

        start() {
            expect.step("start");
        }
    }

    const { core } = await startInteraction(
        Test,
        `
        <div class="test"><div class="inner"></div></div>
        <div class="test"><div class="not-inner"></div></div>
    `,
    );
    expect(core.interactions).toHaveLength(1);
    expect.verifySteps(["start"]);
    expect(core.interactions[0].interaction.el).toBe(queryOne(".test:has(.inner)"));
});

test("stop interactions with selectorHas", async () => {
    class Test extends Interaction {
        static selector = ".test";
        static selectorHas = ".inner";

        start() {
            expect.step("start");
        }

        destroy() {
            expect.step("destroy");
        }
    }

    const { core } = await startInteraction(
        Test,
        `
        <div class="test"><div class="inner"></div><div class="other"></div></div>
    `,
    );
    expect.verifySteps(["start"]);

    queryOne(".inner").remove();
    core.stopInteractions(queryOne(".other"));
    expect.verifySteps(["destroy"]);
});

test("start interactions even if there is a crash when evaluating selectorNotHas", async () => {
    expect.errors(1);
    class Boom extends Interaction {
        static selector = ".test";
        static selectorNotHas = "div:invalid(coucou)";

        setup() {
            expect.step("start boom");
        }
        destroy() {
            expect.step("destroy boom");
        }
    }
    class NotBoom extends Interaction {
        static selector = ".test";

        setup() {
            expect.step("start notboom");
        }
    }

    const { core } = await startInteraction(
        [Boom, NotBoom],
        `<div class="test"><div></div></div>`,
        {
            waitForStart: false,
        },
    );

    await expect(core.isReady).rejects.toThrow(
        "Could not start interaction Boom (invalid selector: '.test' or selectorNotHas: 'div:invalid(coucou)')",
    );
    expect.verifySteps(["start notboom"]);
    await animationFrame();
    expect.verifyErrors([/selectorNotHas: 'div:invalid\(coucou\)'/]);
});

test("start interactions with selectorNotHas", async () => {
    class Test extends Interaction {
        static selector = ".test";
        static selectorNotHas = ".inner";

        start() {
            expect.step("start");
        }
    }

    const { core } = await startInteraction(
        Test,
        `
        <div class="test"><div class="inner"></div></div>
        <div class="test"><div class="not-inner"></div></div>
    `,
    );
    expect(core.interactions).toHaveLength(1);
    expect.verifySteps(["start"]);
    expect(core.interactions[0].interaction.el).toBe(
        queryOne(".test:not(:has(.inner))"),
    );
});

test("stop interactions with selectorNotHas", async () => {
    class Test extends Interaction {
        static selector = ".test";
        static selectorNotHas = ".inner";

        start() {
            expect.step("start");
        }

        destroy() {
            expect.step("destroy");
        }
    }

    const { core } = await startInteraction(Test, `<div class="test"></div>`);
    expect.verifySteps(["start"]);

    const div = document.createElement("div");
    div.className = "inner";
    queryOne(".test").appendChild(div);
    core.stopInteractions(div);
    expect.verifySteps(["destroy"]);
});

test("recover from error as much as possible when applying dynamiccontent", async () => {
    let a = "a";
    let b = "b";
    let c = "c";
    let interaction = null;

    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            _root: {
                "t-att-a": () => a,
                "t-att-b": () => {
                    if (b === "boom") {
                        throw new Error("boom");
                    }
                    return b;
                },
                "t-att-c": () => c,
            },
        };
        setup() {
            interaction = this;
        }
    }

    await startInteraction(Test, `<div class="test"></div>`);
    expect(".test").toHaveOuterHTML(`<div class="test" a="a" b="b" c="c"></div>`);

    a = "aa";
    b = "boom";
    c = "cc";
    expect(() => interaction.updateContent()).toThrow(
        "An error occured while updating dynamic attribute 'b' (in interaction 'Test')",
    );
    expect(".test").toHaveOuterHTML(`<div class="test" a="aa" b="b" c="cc"></div>`);
});

test("global stop does not restart interactions from restored t-out content", async () => {
    class Inner extends Interaction {
        static selector = ".inner";

        setup() {
            expect.step("inner setup");
        }
        destroy() {
            expect.step("inner destroy");
        }
    }
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            _root: { "t-out": () => markup`<span class="dynamic">Hello</span>` },
        };
    }

    const { core } = await startInteraction(
        [Inner, Test],
        `<div class="test"><span class="inner">Hi</span></div>`,
    );
    expect.verifySteps(["inner setup", "inner destroy"]);
    expect(queryOne(".test .dynamic")).toHaveText("Hello");

    core.stopInteractions();
    expect(queryOne(".test .inner")).toHaveText("Hi");
    expect.verifySteps([]);
    expect(core.interactions).toHaveLength(0);
});

test("a crashed setup leaves the interaction retryable", async () => {
    expect.errors(1);
    let boom = true;
    class Test extends Interaction {
        static selector = ".test";

        setup() {
            if (boom) {
                throw new Error("boom");
            }
            expect.step("setup");
        }
    }

    const { core } = await startInteraction(Test, `<div class="test"></div>`, {
        waitForStart: false,
    });
    await expect(core.isReady).rejects.toThrow("boom");
    expect(core.interactions).toHaveLength(0);

    boom = false;
    await core.startInteractions();
    expect.verifySteps(["setup"]);
    expect(core.interactions).toHaveLength(1);
    await animationFrame();
    expect.verifyErrors([/boom/]);
});

test("a crashed async willStart leaves the interaction retryable", async () => {
    expect.errors(1);
    let boom = true;
    class Test extends Interaction {
        static selector = ".test";

        async willStart() {
            if (boom) {
                throw new Error("boom");
            }
        }
        start() {
            expect.step("start");
        }
    }

    const { core } = await startInteraction(Test, `<div class="test"></div>`, {
        waitForStart: false,
    });
    await expect(core.isReady).rejects.toThrow("boom");
    expect(core.interactions).toHaveLength(0);

    boom = false;
    await core.startInteractions();
    expect.verifySteps(["start"]);
    expect(core.interactions).toHaveLength(1);
    await animationFrame();
    expect.verifyErrors([/boom/]);
});

test("interactions are stopped in reverse order", async () => {
    let n = 1;
    class Test extends Interaction {
        static selector = ".test";

        setup() {
            this.n = n++;
            expect.step(`setup ${this.n}`);
        }
        destroy() {
            expect.step(`destroy ${this.n}`);
        }
    }

    const { core } = await startInteraction(
        Test,
        `<div class="test"></div><div class="test"></div>`,
    );
    expect.verifySteps(["setup 1", "setup 2"]);
    core.stopInteractions();
    expect.verifySteps(["destroy 2", "destroy 1"]);
});

test("can mount a component", async () => {
    class Test extends Component {
        static selector = ".test";
        static template = xml`owl component`;
        static props = {};
    }
    const { core } = await startInteraction(Test, `<div class="test"></div>`);
    expect(".test").toHaveInnerHTML(
        `<owl-root contenteditable="false" data-oe-protected="true" style="display: contents;">owl component</owl-root>`,
    );
    core.stopInteractions();
    expect(".test").toHaveOuterHTML(`<div class="test"></div>`);
});

test("a surfaced failure does not make every later isReady reject", async () => {
    expect.errors(1);
    class Boom extends Interaction {
        static selector = ".boom";
        setup() {
            throw new Error("boom");
        }
    }
    class Fine extends Interaction {
        static selector = ".fine";
    }
    const { core } = await startInteraction(
        [Boom, Fine],
        `<div class="boom"></div><div class="fine"></div>`,
        { waitForStart: false },
    );
    await expect(core.isReady).rejects.toThrow("boom");

    // the crash has been surfaced: holding on to it made every later read
    // reject too — the page could never become ready again — and grew the
    // tracked-promise list without bound
    expect(core.proms).toHaveLength(0);
    await core.startInteractions(queryOne(".fine"));
    await core.isReady;
    expect.step("ready again");
    expect.verifySteps(["ready again"]);
    await animationFrame();
    expect.verifyErrors([/boom/]);
});

test("a component that fails to mount leaves no dead root behind", async () => {
    // the failure has to happen after prepareRoot() inserted the <owl-root>:
    // a component whose setup() throws synchronously never gets that far, so
    // it does not exercise this at all
    class Test extends Component {
        static selector = ".test";
        static template = xml`owl component`;
        static props = {};
        setup() {
            onWillStart(async () => {
                throw new Error("boom");
            });
        }
    }
    expect.errors(1);
    const { core } = await startInteraction(Test, `<div class="test"></div>`, {
        waitForStart: false,
    });
    await expect(core.isReady).rejects.toThrow("owl lifecycle");
    // neither the <owl-root> host nor the dead root may survive: the host
    // lingers in the page and the root gets destroyed a second time by the
    // next stopInteractions()
    expect(".test").toHaveOuterHTML(`<div class="test"></div>`);
    expect(core.roots).toHaveLength(0);
    core.stopInteractions();
    expect(".test").toHaveOuterHTML(`<div class="test"></div>`);
    await animationFrame();
    await animationFrame();
    expect.verifyErrors([/boom/]);
});

test("can start interaction in specific el", async () => {
    let n = 0;
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            _root: { "t-att-a": () => "b" },
        };

        setup() {
            n++;
        }
    }

    const { core } = await startInteraction(Test, `<p></p>`);

    expect(n).toBe(0);
    const p = queryOne("p");
    p.innerHTML = `<div class="test">hello</div>`;
    core.startInteractions(queryOne(".test"));
    await animationFrame();
    expect(n).toBe(1);
    expect(p).toHaveInnerHTML(`<div class="test" a="b">hello</div>`);
});

test("can start and stop interaction in specific el", async () => {
    let n = 0;
    class Test extends Interaction {
        static selector = ".test";

        start() {
            n++;
            this.el.dataset.start = "true";
        }
        destroy() {
            n--;
            delete this.el.dataset.start;
        }
    }

    const { core } = await startInteraction(
        Test,
        `
        <p>
            <span class="a test"></span>
            <span class="b"></span>
        </p>`,
    );

    expect(n).toBe(1);
    const p = queryOne("p");
    expect(p).toHaveInnerHTML(
        `<span class="a test" data-start="true"></span> <span class="b"></span>`,
    );
    const b = queryOne("p .b");
    b.classList.add("test");
    await core.startInteractions(b);
    expect(n).toBe(2);
    expect(p).toHaveInnerHTML(
        `<span class="a test" data-start="true"></span> <span class="b test" data-start="true"></span>`,
    );

    core.stopInteractions(b);
    expect(n).toBe(1);
    expect(p).toHaveInnerHTML(
        `<span class="a test" data-start="true"></span> <span class="b test"></span>`,
    );
});

test("does not start interaction in el if not attached", async () => {
    let n = 0;
    class Test extends Interaction {
        static selector = ".test";
        start() {
            n++;
        }
        destroy() {
            n--;
        }
    }

    const { core } = await startInteraction(Test, `<p><span class="test"></span></p>`);
    expect(n).toBe(1);
    const span = queryOne("span.test");
    core.stopInteractions(span);
    expect(n).toBe(0);
    span.remove();
    await core.startInteractions(span);
    expect(n).toBe(0);
});

test("every interaction that fails to start is reported, not just the first", async () => {
    class BoomA extends Interaction {
        static selector = ".a";
        async willStart() {
            throw new Error("boom A");
        }
    }
    class BoomB extends Interaction {
        static selector = ".b";
        async willStart() {
            throw new Error("boom B");
        }
    }
    const { core } = await startInteraction(
        [BoomA, BoomB],
        `<div class="a"></div><div class="b"></div>`,
        { waitForStart: false },
    );
    const reported = [];
    core.reportError = (error) => reported.push(error);
    let caught = null;
    try {
        await core.isReady;
    } catch (error) {
        caught = error;
    }
    expect(caught).toBeInstanceOf(AggregateError);
    expect(caught.errors.map((e) => e.message).sort()).toEqual(["boom A", "boom B"]);
    // the scan and the promise `activate` derives from it carry the same
    // failure: it must not be logged twice
    expect(reported).toHaveLength(1);
});
