// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { BarcodeVideoScanner } from "@web/components/barcode/barcode_video_scanner";
import { Notebook } from "@web/components/notebook/notebook";
import { RecordAutocomplete } from "@web/components/record_selectors/record_autocomplete";
import { ConnectionAbortedError } from "@web/core/network/rpc";
import { Deferred } from "@web/core/utils/concurrency";

test("notebook: activatePage is safe with neither slots nor pages", async () => {
    const nb = /** @type {any} */ (await mountWithCleanup(Notebook));
    expect(nb.disabledPages).toEqual([]);
    await nb.activatePage("whatever");
    expect(nb.state.currentPage).toBe(null);
});

test("notebook: activatePage ignores an id that matches no page", async () => {
    class Parent extends Component {
        static template = xml`<Notebook defaultPage="'a'">
            <t t-set-slot="a" title="'A'" isVisible="true"><p class="pa">a</p></t>
            <t t-set-slot="b" title="'B'" isVisible="true"><p class="pb">b</p></t>
        </Notebook>`;
        static components = { Notebook };
        static props = ["*"];
    }
    const parent = /** @type {any} */ (await mountWithCleanup(Parent));
    const nb = /** @type {any} */ (
        Object.values(parent.__owl__.children).map(
            (c) => /** @type {any} */ (c).component,
        )[0]
    );
    expect(nb.state.currentPage).toBe("a");
    await nb.activatePage("does-not-exist");
    expect(nb.state.currentPage).toBe("a");
    expect(".pa").toHaveCount(1);
    await nb.activatePage("b");
    expect(nb.state.currentPage).toBe("b");
});

test("record autocomplete: a superseded search settles instead of hanging", async () => {
    /** @type {any[]} */
    const proms = [];
    const makeSearch = () => {
        const def = /** @type {any} */ (new Deferred());
        def.abort = (/** @type {boolean} */ rejectError) => {
            if (rejectError) {
                def.reject(new ConnectionAbortedError("fetch abort"));
            }
        };
        def.catch(() => {});
        proms.push(def);
        return def;
    };
    const ra = /** @type {any} */ (Object.create(RecordAutocomplete.prototype));
    ra.props = { update: () => {} };
    ra.search = makeSearch;
    ra.addNames = () => {};
    ra.getIds = () => [];

    /** @type {string[]} */
    const settled = [];
    ra.loadOptionsSource("a").then(() => settled.push("first"));
    ra.loadOptionsSource("ab").then(() => settled.push("second"));

    proms[1].resolve([]);
    await animationFrame();
    await animationFrame();

    // Both invocations settle: the superseded one unwinds through the abort
    // rejection instead of staying pending forever.
    expect(settled.toSorted()).toEqual(["first", "second"]);
});

test("record autocomplete: a real search failure still propagates", async () => {
    const ra = /** @type {any} */ (Object.create(RecordAutocomplete.prototype));
    ra.props = { update: () => {} };
    ra.search = () => Promise.reject(new Error("boom"));
    ra.addNames = () => {};
    ra.getIds = () => [];
    let message = "";
    try {
        await ra.loadOptionsSource("a");
    } catch (error) {
        message = /** @type {Error} */ (error).message;
    }
    expect(message).toBe("boom");
});

test("barcode: the zoom slider is owned by the template", async () => {
    /** @type {any[]} */
    const applied = [];
    const track = {
        getCapabilities: () => ({ zoom: { min: 1, max: 5, step: 1 } }),
        applyConstraints: (/** @type {any} */ c) => {
            applied.push(c.advanced[0].zoom);
            return Promise.resolve();
        },
    };
    /** @type {any} */
    let scanner = null;
    class Probe extends BarcodeVideoScanner {
        setup() {
            super.setup();
            scanner = this;
        }
    }
    class Parent extends Component {
        static template = xml`<div class="probe">
            <Probe t-if="state.on" facingMode="'environment'" onResult="() => {}" onError="() => {}"/>
        </div>`;
        static components = { Probe };
        static props = ["*"];
        setup() {
            this.state = state;
        }
    }
    const state = { on: true };
    const parent = /** @type {any} */ (await mountWithCleanup(Parent));

    expect(".probe input[type=range]").toHaveCount(0);
    scanner.addZoomSlider(track, { zoom: 2 });
    await animationFrame();
    expect(".probe input[type=range]").toHaveCount(1);

    const input = /** @type {HTMLInputElement} */ (
        document.querySelector(".probe input[type=range]")
    );
    input.value = "4";
    input.dispatchEvent(new Event("input"));
    await animationFrame();
    expect(applied).toEqual([4]);
    expect(typeof applied[0]).toBe("number");

    // Unmounting the scanner takes the slider with it.
    state.on = false;
    parent.render(true);
    await animationFrame();
    expect(".probe input[type=range]").toHaveCount(0);
});
