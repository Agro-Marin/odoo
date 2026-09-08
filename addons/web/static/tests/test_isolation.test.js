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

class SyntheticCounter extends Component {
    static props = ["onClick"];
    static template = xml`<button t-on-click.synthetic="() => this.props.onClick()">go</button>`;
}

/** @type {string[]} */
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
