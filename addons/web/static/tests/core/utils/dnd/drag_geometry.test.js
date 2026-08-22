// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { canStartDrag, handleEdgeScrolling } from "@web/core/utils/dnd/drag_geometry";

describe.current.tags("headless");

/**
 * @param {{ tolerance?: number, from?: {x: number, y: number}, to: {x: number, y: number} }} spec
 */
function toleranceCtx({ tolerance = 10, from = { x: 0, y: 0 }, to }) {
    return /** @type {any} */ ({
        tolerance,
        pointer: { ...to },
        current: { initialPosition: { ...from } },
    });
}

/**
 * @param {{ vertical?: boolean }} [opts]
 */
function scrollable({ vertical = true } = {}) {
    const box = document.createElement("div");
    box.style.cssText = vertical
        ? "height:100px;width:100px;overflow:auto;position:relative;"
        : "height:100px;width:100px;overflow:auto;position:relative;";
    const inner = document.createElement("div");
    inner.style.cssText = vertical
        ? "height:1000px;width:50px;"
        : "height:50px;width:1000px;";
    box.appendChild(inner);
    getFixture().appendChild(box);
    return box;
}

/**
 * @param {{
 * box: HTMLElement,
 * pointer: {x: number, y: number},
 * speed?: number,
 * threshold?: number,
 * direction?: string,
 * vertical?: boolean,
 * }} spec
 */
function scrollCtx({
    box,
    pointer,
    speed = 10,
    threshold = 30,
    direction,
    vertical = true,
}) {
    const rect = box.getBoundingClientRect();
    const ctx = /** @type {any} */ ({
        pointer: { ...pointer },
        edgeScrolling: { enabled: true, speed, threshold, direction },
        current: {
            container: box,
            rectsDirty: false,
            scrollParentY: vertical ? box : null,
            scrollParentX: vertical ? null : box,
            scrollParentYRect: vertical ? rect : null,
            scrollParentXRect: vertical ? null : rect,
        },
    });
    return ctx;
}

test("a move of exactly the tolerance starts the drag", () => {
    const ctx = toleranceCtx({ tolerance: 10, to: { x: 6, y: 8 } });
    expect(canStartDrag(ctx)).toBe(true);

    const justUnder = toleranceCtx({ tolerance: 10, to: { x: 6, y: 7.99 } });
    expect(canStartDrag(justUnder)).toBe(false);
});

test("an absent tolerance means any move starts the drag", () => {
    const absent = /** @type {any} */ ({
        pointer: { x: 3, y: 4 },
        current: { initialPosition: { x: 0, y: 0 } },
    });
    expect("tolerance" in absent).toBe(false);
    expect(canStartDrag(absent)).toBe(true);

    const zero = toleranceCtx({ tolerance: 0, to: { x: 0, y: 0 } });
    expect(canStartDrag(zero)).toBe(true);
});

test("scroll distance is proportional to speed and to the frame's deltaTime", () => {
    const box = scrollable();
    box.scrollTop = 500;
    const rect = box.getBoundingClientRect();
    const at = { x: rect.x + 50, y: rect.bottom };

    const slow = scrollCtx({ box, pointer: at, speed: 10, threshold: 30 });
    handleEdgeScrolling(16, slow, { updateRects: () => {}, onDrag: () => {} });
    const movedAtSpeed10 = box.scrollTop - 500;

    box.scrollTop = 500;
    const fast = scrollCtx({ box, pointer: at, speed: 20, threshold: 30 });
    handleEdgeScrolling(16, fast, { updateRects: () => {}, onDrag: () => {} });
    const movedAtSpeed20 = box.scrollTop - 500;

    expect(movedAtSpeed10).toBeCloseTo(10, { margin: 1 });
    expect(movedAtSpeed20).toBeCloseTo(20, { margin: 1 });

    box.scrollTop = 500;
    const longFrame = scrollCtx({ box, pointer: at, speed: 10, threshold: 30 });
    handleEdgeScrolling(32, longFrame, { updateRects: () => {}, onDrag: () => {} });
    expect(box.scrollTop - 500).toBeCloseTo(20, { margin: 1 });
});

test("a pointer past the edge scrolls at the capped speed, not faster", () => {
    const box = scrollable();
    const rect = box.getBoundingClientRect();

    box.scrollTop = 500;
    const atEdge = scrollCtx({
        box,
        pointer: { x: rect.x + 50, y: rect.bottom },
        speed: 10,
    });
    handleEdgeScrolling(16, atEdge, { updateRects: () => {}, onDrag: () => {} });
    const atEdgeMoved = box.scrollTop - 500;

    box.scrollTop = 500;
    const wayPast = scrollCtx({
        box,
        pointer: { x: rect.x + 50, y: rect.bottom + 500 },
        speed: 10,
    });
    handleEdgeScrolling(16, wayPast, { updateRects: () => {}, onDrag: () => {} });
    const pastMoved = box.scrollTop - 500;

    expect(pastMoved).toBeCloseTo(atEdgeMoved, { margin: 1 });
});

test("onDrag fires when a scroll happened, and not when none did", () => {
    const box = scrollable();
    const rect = box.getBoundingClientRect();

    box.scrollTop = 500;
    const scrolling = scrollCtx({ box, pointer: { x: rect.x + 50, y: rect.bottom } });
    handleEdgeScrolling(16, scrolling, {
        updateRects: () => {},
        onDrag: () => expect.step("onDrag"),
    });
    expect.verifySteps(["onDrag"]);
    expect(scrolling.current.rectsDirty).toBe(true, {
        message: "a scroll invalidates the rects it measured against",
    });

    const idle = scrollCtx({
        box,
        pointer: { x: rect.x + 50, y: rect.y + 50 },
    });
    handleEdgeScrolling(16, idle, {
        updateRects: () => {},
        onDrag: () => expect.step("onDrag"),
    });
    expect.verifySteps([]);
});

test("dirty rects are refreshed and reported even without a scroll", () => {
    const box = scrollable();
    const rect = box.getBoundingClientRect();
    const ctx = scrollCtx({ box, pointer: { x: rect.x + 50, y: rect.y + 50 } });
    ctx.current.rectsDirty = true;

    handleEdgeScrolling(16, ctx, {
        updateRects: () => expect.step("updateRects"),
        onDrag: () => expect.step("onDrag"),
    });
    expect.verifySteps(["updateRects", "onDrag"], {
        message: "the drag is told even when only the geometry moved",
    });
    expect(ctx.current.rectsDirty).toBe(false);
});
