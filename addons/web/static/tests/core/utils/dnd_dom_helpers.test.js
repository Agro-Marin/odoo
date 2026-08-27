// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import {
    makeCleanupManager,
    makeDOMHelpers,
} from "@web/core/utils/dnd/draggable_hook_builder_utils";

describe.current.tags("headless");

function helpers() {
    const cleanup = makeCleanupManager();
    return { cleanup, dom: makeDOMHelpers(cleanup) };
}

/**
 * @param {string} className
 * @returns {HTMLElement}
 */
function element(className = "") {
    const el = document.createElement("div");
    el.className = className;
    getFixture().appendChild(el);
    return el;
}

describe("addClass", () => {
    test("gives back a class the element already carried", () => {
        const el = element("o_hierarchy_node shadow");
        const { cleanup, dom } = helpers();

        dom.addClass(el, "o_hierarchy_dragged", "shadow");
        expect(el.className).toBe("o_hierarchy_node shadow o_hierarchy_dragged");

        cleanup.cleanup();
        expect(el.className).toBe("o_hierarchy_node shadow");
    });

    test("removes what it did add", () => {
        const el = element("a");
        const { cleanup, dom } = helpers();
        dom.addClass(el, "b", "c");
        expect(el.classList.contains("b")).toBe(true);
        cleanup.cleanup();
        expect(el.className).toBe("a");
    });

    test("adding only classes that are already there undoes nothing", () => {
        const el = element("a b");
        const { cleanup, dom } = helpers();
        dom.addClass(el, "a", "b");
        cleanup.cleanup();
        expect(el.className).toBe("a b");
    });
});

describe("removeClass", () => {
    test("restores what it removed", () => {
        const el = element("a b");
        const { cleanup, dom } = helpers();
        dom.removeClass(el, "b");
        expect(el.className).toBe("a");
        cleanup.cleanup();
        expect(el.className).toBe("a b");
    });
});

describe("addClass and removeClass on the same element", () => {
    test("both undo, in either order", () => {
        for (const addFirst of [true, false]) {
            const el = element("keep drop");
            const { cleanup, dom } = helpers();
            if (addFirst) {
                dom.addClass(el, "added");
                dom.removeClass(el, "drop");
            } else {
                dom.removeClass(el, "drop");
                dom.addClass(el, "added");
            }
            cleanup.cleanup();
            expect(el.classList.contains("keep")).toBe(true, {
                message: `${addFirst}`,
            });
            expect(el.classList.contains("drop")).toBe(true, {
                message: `${addFirst}`,
            });
            expect(el.classList.contains("added")).toBe(false, {
                message: `${addFirst}`,
            });
        }
    });
});
