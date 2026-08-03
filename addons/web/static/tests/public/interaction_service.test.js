// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    Component,
    markup,
    onWillDestroy,
    onWillStart,
    onWillUnmount,
    xml,
} from "@odoo/owl";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { Interaction } from "@web/public/interaction";

import { startInteraction } from "./helpers.js";

describe.current.tags("interaction_dev");

test("properly fallback to body when we have no match for wrapwrap", async () => {
    const env = await makeMockEnv();
    expect(env.services["public.interactions"].el).toBe(
        /** @type {HTMLElement} */ (document.querySelector("body")),
    );
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
    /** @type {any} */
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
        "An error occured while updating dynamic attribute 'b' (selector '_root') (in interaction 'Test')",
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

test("a root whose host was wiped is still collected by stopInteractions", async () => {
    class C extends Component {
        static template = xml`comp`;
        static props = {};
    }
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = { ".host": { "t-component": C } };
    }
    const { core } = await startInteraction(
        Test,
        `<div class="test"><div class="host"></div></div>`,
    );
    expect(core.roots).toHaveLength(1);
    // anything that rewrites the host detaches the <owl-root>; matching on it
    // alone then left the root -- and the live component under it -- behind
    queryOne(".host").innerHTML = "";
    core.stopInteractions(queryOne(".host"));
    expect(core.roots).toHaveLength(0);
});

test("a live root mounted outside the stopped host is left alone", async () => {
    class C extends Component {
        static template = xml`comp`;
        static props = {};
    }
    class Test extends Interaction {
        static selector = ".test";
        start() {
            // the <owl-root> lands as a SIBLING of the host, not inside it
            this.mountComponent(queryOne(".host"), C, null, "afterend");
        }
    }
    const { core } = await startInteraction(
        Test,
        `<div class="test"><div class="host"></div></div>`,
    );
    await animationFrame();
    const rootEl = core.roots[0].el;
    // its owning interaction is not being stopped either: matching on the host
    // alone would destroy a live component out from under its owner
    core.stopInteractions(queryOne(".host"));
    expect(core.roots).toHaveLength(1);
    expect(core.interactions).toHaveLength(1);
    // once detached it can no longer be placed by containment, and the host
    // has to answer for it
    rootEl.remove();
    core.stopInteractions(queryOne(".host"));
    expect(core.roots).toHaveLength(0);
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
    /** @type {any[]} */
    const reported = [];
    /** @param {any} error */
    core.reportError = (error) => reported.push(error);
    let caught = null;
    try {
        await core.isReady;
    } catch (error) {
        caught = error;
    }
    expect(caught).toBeInstanceOf(AggregateError);
    expect(caught.errors.map((/** @type {Error} */ e) => e.message).sort()).toEqual([
        "boom A",
        "boom B",
    ]);
    // the scan and the promise `activate` derives from it carry the same
    // failure: it must not be logged twice
    expect(reported).toHaveLength(1);
});

test("a page-wide stop reaps an interaction whose element left the document", async () => {
    let destroys = 0;
    class Test extends Interaction {
        static selector = ".test";
        destroy() {
            destroys++;
        }
    }
    const { core } = await startInteraction(
        Test,
        `<div id="host"><div class="test"></div></div>`,
    );
    expect(core.interactions).toHaveLength(1);
    // dropped without its interaction being stopped: `contains` can no longer
    // see it, so its listeners, timers and observers used to run for the rest
    // of the page's life
    queryOne(".test").remove();
    core.stopInteractions();
    expect(destroys).toBe(1);
    expect(core.interactions).toHaveLength(0);
});

test("a scoped stop still leaves a detached interaction alone", async () => {
    let destroys = 0;
    class Test extends Interaction {
        static selector = ".test";
        destroy() {
            destroys++;
        }
    }
    const { core } = await startInteraction(
        Test,
        `<div id="host"><div class="test"></div></div><div id="other"></div>`,
    );
    // an element may be detached on its way somewhere else; only a page-wide
    // stop is entitled to assume it is gone for good
    queryOne(".test").remove();
    core.stopInteractions(queryOne("#other"));
    expect(destroys).toBe(0);
    expect(core.interactions).toHaveLength(1);
});

test("a component mounted by t-component is stopped with its subtree", async () => {
    let destroys = 0;
    class Comp extends Component {
        static template = xml`<b>c</b>`;
        static props = {};
        setup() {
            onWillDestroy(() => {
                destroys++;
            });
        }
    }
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            ".host": { "t-component": () => [Comp, {}] },
        };
    }
    const { core } = await startInteraction(
        Test,
        `<div class="test"><div class="host"></div></div>`,
    );
    expect("owl-root b").toHaveCount(1);
    expect(core.roots).toHaveLength(1);
    // the host subtree goes: the component living in it must go too, rather
    // than keep running on markup nobody can reach
    core.stopInteractions(queryOne(".host"));
    expect(destroys).toBe(1);
    expect("owl-root").toHaveCount(0);
    expect(core.roots).toHaveLength(0);
});

test("a t-component root is forgotten when its interaction is destroyed", async () => {
    class Comp extends Component {
        static template = xml`<b>c</b>`;
        static props = {};
    }
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            _root: { "t-component": () => [Comp, {}] },
        };
    }
    const { core } = await startInteraction(Test, `<div class="test"></div>`);
    expect(core.roots).toHaveLength(1);
    core.stopInteractions();
    expect("owl-root").toHaveCount(0);
    expect(core.roots).toHaveLength(0);
});

test("insert(): a throwing nested destroy still removes the inserted element", async () => {
    class Bad extends Interaction {
        static selector = ".bad";
        destroy() {
            throw new Error("boom");
        }
    }
    class Test extends Interaction {
        static selector = ".test";
        start() {
            const el = document.createElement("div");
            el.className = "inserted";
            el.innerHTML = `<span class="bad"></span>`;
            // outside this.el, so stopping .test alone leaves the nested
            // interaction for the insert() cleanup to deal with
            this.insert(el, queryOne("#elsewhere"));
        }
    }
    const { core } = await startInteraction(
        [Bad, Test],
        `<div class="test"></div><div id="elsewhere"></div>`,
    );
    expect(".inserted").toHaveCount(1);
    let caught = null;
    try {
        core.stopInteractions(queryOne(".test"));
    } catch (error) {
        caught = error;
    }
    expect(caught).toBeInstanceOf(AggregateError);
    // stopInteractions reports a failing nested destroy() by throwing: the
    // subtree used to be stranded in the page, outliving the interaction that
    // put it there
    expect(".inserted").toHaveCount(0);
});

test("a stop rooted above the service's own root also reaps a detached interaction", async () => {
    let destroys = 0;
    class Test extends Interaction {
        static selector = ".test";
        destroy() {
            destroys++;
        }
    }
    const { core } = await startInteraction(Test, `<div class="test"></div>`);
    queryOne(".test").remove();
    // document.body contains #wrapwrap: just as page-wide as the no-arg form
    core.stopInteractions(document.body);
    expect(destroys).toBe(1);
    expect(core.interactions).toHaveLength(0);
});

test("a page-wide stop reaps a component root whose host left the document", async () => {
    let destroys = 0;
    class Comp extends Component {
        static template = xml`<b>c</b>`;
        static props = {};
        setup() {
            onWillDestroy(() => {
                destroys++;
            });
        }
    }
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            ".host": { "t-component": () => [Comp, {}] },
        };
    }
    const { core } = await startInteraction(
        Test,
        `<div class="test"><div class="host"></div></div>`,
    );
    expect(core.roots).toHaveLength(1);
    // dropped without stopping anything: `contains` can no longer reach the
    // root, so the component used to keep running for the page's lifetime
    queryOne(".host").remove();
    core.stopInteractions();
    expect(destroys).toBe(1);
    expect(core.roots).toHaveLength(0);
});

test("a component whose onWillUnmount throws does not strand the other roots", async () => {
    // owl runs `onWillUnmount` uncaught (only `onWillDestroy` is wrapped), so
    // this is the ordinary way a root teardown fails: a hook touching something
    // that has already gone away.
    class Boom extends Component {
        static template = xml`boom`;
        static props = {};
        static selector = ".boom";
        setup() {
            onWillUnmount(() => {
                throw new Error("willUnmount blew up");
            });
        }
    }
    class Fine extends Component {
        static template = xml`fine`;
        static props = {};
        static selector = ".fine";
        setup() {
            onWillDestroy(() => expect.step("fine destroyed"));
        }
    }
    const { core } = await startInteraction(
        [Fine, Boom],
        `<div class="fine"></div><div class="boom"></div>`,
    );
    expect(core.roots).toHaveLength(2);

    // the failure is reported, like a failing interaction destroy()
    expect(() => core.stopInteractions()).toThrow(
        "Could not destroy some interactions",
    );
    // ...but ONE of them used to abort the loop: every remaining root stayed
    // mounted, the whole list stayed tracked, and both <owl-root> hosts stayed
    // in the page with nothing left to ever remove them
    expect.verifySteps(["fine destroyed"]);
    expect(core.roots).toHaveLength(0);
    expect(".fine owl-root").toHaveCount(0);
    expect(".boom owl-root").toHaveCount(0);
});

describe("stopping by registry name", () => {
    test("stops both flavours the registry can hold, not just Interactions", async () => {
        class Inter extends Interaction {
            static selector = ".inter";
            destroy() {
                expect.step("interaction stopped");
            }
        }
        class Comp extends Component {
            static template = xml`c`;
            static props = {};
            static selector = ".comp";
            setup() {
                onWillDestroy(() => expect.step("component stopped"));
            }
        }
        const { core } = await startInteraction(
            [Inter, Comp],
            `<div class="inter"></div><div class="comp"></div>`,
        );
        expect(core.interactions).toHaveLength(1);
        expect(core.roots).toHaveLength(1);

        // a public component is tracked in `roots`, never in `interactions`, so
        // a by-name stop that walks only the latter could not touch it at all
        core.stopInteractionsByName("Comp");
        expect.verifySteps(["component stopped"]);
        expect(core.roots).toHaveLength(0);
        expect(".comp owl-root").toHaveCount(0);
        expect(core.interactions).toHaveLength(1);

        core.stopInteractionsByName("Inter");
        expect.verifySteps(["interaction stopped"]);
        expect(core.interactions).toHaveLength(0);
    });

    test("a failing destroy does not leave the others behind", async () => {
        class Boom extends Interaction {
            static selector = ".boom";
            destroy() {
                if (this.el.classList.contains("first")) {
                    throw new Error("destroy blew up");
                }
                expect.step("sibling stopped");
            }
        }
        const { core } = await startInteraction(
            Boom,
            `<div class="boom first"></div><div class="boom"></div>`,
        );
        expect(core.interactions).toHaveLength(2);
        // it used to abort on the throw, leaving `this.interactions` untouched
        // (the rebuilt list was never assigned) and the remaining match running
        expect(() => core.stopInteractionsByName("Boom")).toThrow(
            "Could not destroy some interactions",
        );
        expect.verifySteps(["sibling stopped"]);
        expect(core.interactions).toHaveLength(0);
    });
});

test("stopDisconnectedInteractions reaps every detached interaction", async () => {
    class Test extends Interaction {
        static selector = ".test";
        destroy() {
            expect.step(`stopped ${this.el.dataset.n}`);
        }
    }
    const { core } = await startInteraction(
        Test,
        `<div class="test" data-n="1"></div><div class="test" data-n="2"></div>
         <div class="test" data-n="3"></div>`,
    );
    expect(core.interactions).toHaveLength(3);
    for (const el of document.querySelectorAll(".test")) {
        el.remove();
    }
    // characterises the primitive the website builder used to open-code against
    // the service's internals; every detached one goes, none is skipped, and
    // teardown runs newest-first like every other stop path in the service
    core.stopDisconnectedInteractions();
    expect.verifySteps(["stopped 3", "stopped 2", "stopped 1"]);
    expect(core.interactions).toHaveLength(0);
});

test("stopDisconnectedInteractions also reaps detached component roots", async () => {
    class Comp extends Component {
        static template = xml`c`;
        static props = {};
        static selector = ".comp";
        setup() {
            onWillDestroy(() => expect.step("component stopped"));
        }
    }
    const { core } = await startInteraction(Comp, `<div class="comp"></div>`);
    expect(core.roots).toHaveLength(1);
    /** @type {HTMLElement} */ (document.querySelector(".comp")).remove();
    // a public component lives in `roots`, never in `interactions`, so a reaper
    // walking only the latter left its owl root mounted on detached DOM forever
    core.stopDisconnectedInteractions();
    expect.verifySteps(["component stopped"]);
    expect(core.roots).toHaveLength(0);
});

test("a page-wide stop reaps an interaction living in another document", async () => {
    // `isConnected` is true for a node in a document of its own, and
    // `document.body.contains()` is false across documents, so such an
    // interaction matched neither half of the old stop predicate and ran
    // forever. `_window` resolves to `defaultView || window`, so it had a live
    // listener on the REAL window -- which is how one test's resize handler
    // went on firing inside every later suite.
    let destroys = 0;
    class Test extends Interaction {
        static selector = ".test";
        dynamicContent = {
            _window: { "t-on-resize": () => expect.step("resized") },
        };
        destroy() {
            destroys++;
        }
    }
    const { core } = await startInteraction(Test, `<div class="test"></div>`);

    const foreign = document.implementation.createHTMLDocument();
    foreign.body.innerHTML = `<div class="test"></div>`;
    expect(foreign.defaultView).toBe(null);
    await core.startInteractions(/** @type {any} */ (foreign.body));
    expect(core.interactions).toHaveLength(2);

    window.dispatchEvent(new Event("resize"));
    await animationFrame();
    expect.verifySteps(["resized", "resized"]);

    core.stopInteractions();

    expect(destroys).toBe(2);
    expect(core.interactions).toHaveLength(0);
    window.dispatchEvent(new Event("resize"));
    await animationFrame();
    expect.verifySteps([]);
});
