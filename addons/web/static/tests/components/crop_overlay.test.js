// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { CropOverlay } from "@web/components/barcode/crop_overlay";
import { browser } from "@web/core/browser/browser";

const STORAGE_KEY = "o-barcode-scanner-overlay";

/**
 * @param {{ onResize?: Function }} [hooks]
 */
function makeHost({ onResize = () => {} } = {}) {
    class Host extends Component {
        static props = ["*"];
        static components = { CropOverlay };
        static template = xml`
            <CropOverlay isReady="state.isReady" onResize.bind="onResize">
                <div style="width: 300px; height: 200px;">video</div>
            </CropOverlay>
            <span class="tick" t-esc="state.tick"/>
        `;
        setup() {
            this.state = useState({ isReady: true, tick: 0 });
        }
        onResize(area) {
            onResize(area);
        }
    }
    return Host;
}

function countStorageWrites() {
    const counter = { writes: 0 };
    patchWithCleanup(browser.localStorage, {
        setItem(key, value) {
            if (key === STORAGE_KEY) {
                counter.writes++;
            }
            return super.setItem(key, value);
        },
    });
    return counter;
}

test("unrelated re-renders do not persist or re-notify the crop area", async () => {
    const storage = countStorageWrites();
    let resizes = 0;
    const host = await mountWithCleanup(makeHost({ onResize: () => resizes++ }));
    await animationFrame();

    const afterMount = { writes: storage.writes, resizes };
    for (let i = 0; i < 3; i++) {
        host.state.tick++;
        await animationFrame();
    }

    expect(storage.writes - afterMount.writes).toBe(0);
    expect(resizes - afterMount.resizes).toBe(0);
});

test("the crop area is published once, and not republished unchanged", async () => {
    /** @type {any[]} */
    const areas = [];
    const host = await mountWithCleanup(
        makeHost({ onResize: (area) => areas.push(area) }),
    );
    await animationFrame();

    expect(areas.length).toBe(1);
    expect(Object.keys(areas[0]).toSorted()).toEqual(["height", "width", "x", "y"]);

    // Re-arming the overlay recomputes the geometry, but an identical area is
    // not pushed at the consumer a second time.
    host.state.isReady = false;
    await animationFrame();
    host.state.isReady = true;
    await animationFrame();
    expect(areas.length).toBe(1);
});

test("a drag persists the position exactly once, on pointer up", async () => {
    const storage = countStorageWrites();
    await mountWithCleanup(makeHost());
    await animationFrame();
    expect(storage.writes).toBe(0);

    const icon = document.querySelector(".o_crop_icon");
    const container = document.querySelector(".o_crop_container");
    icon.dispatchEvent(
        new PointerEvent("pointerdown", { bubbles: true, pointerId: 1 }),
    );
    for (const clientX of [120, 140, 160]) {
        container.dispatchEvent(
            new PointerEvent("pointermove", { bubbles: true, clientX, clientY: 80 }),
        );
    }
    expect(storage.writes).toBe(0);

    container.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    expect(storage.writes).toBe(1);

    // A stray pointerup with no drag in progress must not write again.
    container.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    expect(storage.writes).toBe(1);
});
