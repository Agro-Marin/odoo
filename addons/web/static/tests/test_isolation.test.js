import { expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";

const seen = { win: 0, doc: 0, body: 0 };

test("a test's window, document and body listeners are registered", () => {
    window.addEventListener("test-isolation-probe", () => seen.win++);
    document.addEventListener("test-isolation-probe", () => seen.doc++);
    document.body.addEventListener("test-isolation-probe", () => seen.body++);
    window.dispatchEvent(new Event("test-isolation-probe"));
    document.dispatchEvent(new Event("test-isolation-probe"));
    document.body.dispatchEvent(new Event("test-isolation-probe"));
    expect(seen).toEqual({ win: 1, doc: 1, body: 1 });
});

test("none of them survives into the next test", () => {
    window.dispatchEvent(new Event("test-isolation-probe"));
    document.dispatchEvent(new Event("test-isolation-probe"));
    document.body.dispatchEvent(new Event("test-isolation-probe"));
    expect(seen).toEqual({ win: 1, doc: 1, body: 1 });
});

// Owl installs ONE delegation listener per event type on the document and
// memoizes that it has, so it never reinstalls one that is taken away. It is
// therefore the exception to the rule the two tests above pin, and the only
// listener `trackTestListeners` must not clean up: remove it and every
// `t-on-*.synthetic` handler in the page dies for the rest of the run, without
// an error -- the elements keep their `__event__synthetic_*` data and the click
// still reaches the document.
//
// It went unnoticed because the exemption recognised the listener by the name
// `nativeToSyntheticEvent`, which the bundled test page minifies to `i=>On(e,i)`.
// These two tests are what a name-based check cannot be: they exercise a real
// synthetic handler twice, and the second one is the assertion.

class SyntheticCounter extends Component {
    static props = ["onClick"];
    static template = xml`<button t-on-click.synthetic="() => this.props.onClick()">go</button>`;
}

const syntheticClicks = [];

async function clickSyntheticButton() {
    await mountWithCleanup(SyntheticCounter, {
        props: { onClick: () => syntheticClicks.push("click") },
    });
    await contains("button").click();
}

test("a synthetic event handler fires in the first test that uses one", async () => {
    await clickSyntheticButton();
    expect(syntheticClicks).toEqual(["click"]);
});

test("and in every test after it", async () => {
    await clickSyntheticButton();
    expect(syntheticClicks).toEqual(["click", "click"]);
});
