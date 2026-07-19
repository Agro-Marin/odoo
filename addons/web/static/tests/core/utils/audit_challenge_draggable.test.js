// @ts-check

/**
 * AUDIT CHALLENGE — the drag hook has TWO dispatch paths with different safety
 * contracts, and a user-supplied callback reaches the unguarded one.
 *
 * `callHandler` (draggable_hook_builder.js) wraps `params.*` callbacks in
 * try/catch and calls `dragEnd(null, true)` on throw, so cleanup still runs —
 * this is why a throwing `onDrop` passed to `useSortable` is safe (asserted
 * below as the control).
 *
 * But `nested_sortable` assigns the user-supplied `isAllowed` onto the context
 * (`ctx.isAllowed = params.isAllowed`) and then invokes it DIRECTLY from
 * `_isAllowedNodeMove`, bypassing `callHandler` entirely. A throw there escapes
 * `dragEnd` before `cleanup.cleanup()` runs — leaving `document.body` with
 * `pe-none`/`user-select-none` (nothing on the page is clickable) and the
 * window-level pointer/keydown listeners bound for the rest of the session.
 */

import { expect, test } from "@odoo/hoot";
import { Component, useRef, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useNestedSortable } from "@web/core/utils/dnd/nested_sortable";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";

const LIST_TEMPLATE = xml`
    <div t-ref="root" class="root">
        <ul class="list">
            <li t-foreach="[1, 2, 3]" t-as="i" t-key="i" class="item">
                <span t-esc="i"/>
            </li>
        </ul>
    </div>`;

test("control: a throwing params.onDrop goes through the guarded dispatcher", async () => {
    expect.errors(1);
    class List extends Component {
        static template = LIST_TEMPLATE;
        static props = ["*"];
        setup() {
            useSortable({
                ref: useRef("root"),
                elements: ".item",
                onDrop() {
                    throw new Error("boom from onDrop");
                },
            });
        }
    }
    await mountWithCleanup(List);
    await contains(".item:first-child").dragAndDrop(".item:nth-child(2)");

    // `callHandler` caught it and ran dragEnd(null, true) -> cleanup.
    expect(document.body).not.toHaveClass("pe-none");
    expect(document.body).not.toHaveClass("user-select-none");
    expect.verifyErrors(["boom from onDrop"]);
});

test("a throwing isAllowed still tears the drag session down", async () => {
    expect.errors(1);
    class List extends Component {
        static template = LIST_TEMPLATE;
        static props = ["*"];
        setup() {
            useNestedSortable({
                ref: useRef("root"),
                elements: ".item",
                isAllowed() {
                    throw new Error("boom from isAllowed");
                },
            });
        }
    }
    await mountWithCleanup(List);
    await contains(".item:first-child").dragAndDrop(".item:nth-child(2)");

    // Currently these fail: the throw escapes before cleanup.cleanup(), so the
    // body keeps the drag classes and the page is permanently unclickable.
    expect(document.body).not.toHaveClass("pe-none");
    expect(document.body).not.toHaveClass("user-select-none");
    expect.verifyErrors(["boom from isAllowed"]);
});
