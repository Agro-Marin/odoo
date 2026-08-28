// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { DragSession } from "@web/core/utils/dnd/drag_session";
import { DEFAULT_DEFAULT_PARAMS } from "@web/core/utils/dnd/draggable_hook_builder_utils";
import {
    applyParamsToContext,
    makeDraggableContext,
} from "@web/core/utils/dnd/draggable_hook_params";

describe.current.tags("headless");

/** @param {string} reason */
const makeError = (reason) => new Error(`Error in hook useProbe: ${reason}.`);

/**
 * @returns {{ root: HTMLElement, items: HTMLElement[] }}
 */
function makeTree() {
    const root = document.createElement("div");
    /** @type {HTMLElement} */ (getFixture()).appendChild(root);
    const list = document.createElement("ul");
    root.appendChild(list);
    const items = [0, 1, 2].map(() => {
        const li = document.createElement("li");
        li.className = "item";
        list.appendChild(li);
        return li;
    });
    return { root, items };
}

/**
 * @param {Record<string, any>} [params]
 * @param {Record<string, any>} [hookParams]
 */
function makeSession(params = {}, hookParams = {}) {
    const { root, items } = makeTree();
    const state = { dragging: false, willDrag: false };
    const ref = { el: root };
    const ctx = makeDraggableContext(ref, state);
    applyParamsToContext(
        ctx,
        { ...DEFAULT_DEFAULT_PARAMS, elements: ".item", enable: () => true },
        {},
        makeError,
    );
    const session = new DragSession({
        ctx,
        state,
        params: { ref, elements: ".item", ...params },
        hookParams,
    });
    const throttled = /** @type {any} */ (
        (/** @type {any} */ ev) => session.onPointerMove(ev)
    );
    throttled.cancel = () => expect.step("throttle.cancel");
    session.throttledOnPointerMove = throttled;
    return { session, ctx, state, root, items };
}

/**
 * @param {string} type
 * @param {Record<string, any>} [init]
 */
function pointer(type, init = {}) {
    return new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        button: 0,
        ...init,
    });
}

test("willStartDrag adopts the pressed element and arms the drag", () => {
    const { session, ctx, state, root, items } = makeSession();
    session.willStartDrag(items[1]);
    expect(ctx.current.element).toBe(items[1]);
    expect(ctx.current.container).toBe(root);
    expect(state.willDrag).toBe(true);
    expect(state.dragging).toBe(false, { message: "armed is not yet dragging" });
});

test("willStartDrag ignores a target outside the element selector", () => {
    const { session, ctx, state } = makeSession();
    const stray = document.createElement("div");
    session.willStartDrag(stray);
    expect(ctx.current.element).toBe(/** @type {any} */ (undefined));
    expect(state.willDrag).toBe(false);
});

test("cleanup replaces ctx.current wholesale so nothing survives the drag", () => {
    const { session, ctx, items } = makeSession();
    session.willStartDrag(items[0]);
    ctx.current.leftover = "should not survive";
    session.cleanup.cleanup();
    expect(ctx.current.element).toBe(/** @type {any} */ (undefined));
    expect(ctx.current.leftover).toBe(undefined, {
        message: "a per-drag key must not reach the next drag",
    });
});

/**
 * @param {string[]} names
 * @returns {Record<string, any>}
 */
function buildHandlers(...names) {
    /** @type {Record<string, any>} */
    const h = {};
    for (const name of names) {
        h[name] = () => {
            expect.step(`build:${name}`);
            return {};
        };
    }
    return h;
}

test("a builder handler that returns nothing does not reach the caller's", () => {
    const { session, state, items } = makeSession(
        { onDragEnd: () => expect.step("caller:onDragEnd") },
        {
            onDragEnd: () => {
                expect.step("build:onDragEnd");
            },
        },
    );
    session.willStartDrag(items[0]);
    state.dragging = true;
    session.dragEnd(null);
    expect.verifySteps(["build:onDragEnd"]);
});

test("dragEnd on an armed-but-not-dragging session fires no handler at all", () => {
    const { session, items } = makeSession(
        { onDrop: () => expect.step("caller:onDrop") },
        buildHandlers("onDrop", "onDragEnd"),
    );
    session.willStartDrag(items[0]);
    session.dragEnd(items[1]);
    expect.verifySteps([], {
        message: "a press that never became a drag is not a drop",
    });
});

test("a completed drag runs drop then dragEnd, each through both levels", () => {
    const { session, state, items } = makeSession(
        {
            onDrop: () => expect.step("caller:onDrop"),
            onDragEnd: () => expect.step("caller:onDragEnd"),
        },
        buildHandlers("onDrop", "onDragEnd"),
    );
    session.willStartDrag(items[0]);
    state.dragging = true;
    session.dragEnd(items[1]);
    expect.verifySteps([
        "build:onDrop",
        "caller:onDrop",
        "build:onDragEnd",
        "caller:onDragEnd",
    ]);
});

test("dragEnd in an error state skips both handlers but still cleans up", () => {
    const { session, state, ctx, items } = makeSession(
        { onDrop: () => expect.step("caller:onDrop") },
        buildHandlers("onDrop", "onDragEnd"),
    );
    session.willStartDrag(items[0]);
    state.dragging = true;
    session.dragEnd(items[1], true);
    expect.verifySteps([], { message: "no drop, no dragEnd" });
    expect(state.dragging).toBe(false, { message: "cleanup still ran" });
    expect(ctx.current.element).toBe(/** @type {any} */ (undefined));
});

test("a drop onto a disconnected element is withheld, but dragEnd is not", () => {
    const { session, state, items } = makeSession(
        {},
        buildHandlers("onDrop", "onDragEnd"),
    );
    session.willStartDrag(items[0]);
    state.dragging = true;
    items[0].remove();
    session.dragEnd(items[1]);
    expect.verifySteps(["build:onDragEnd"], {
        message: "dropping a row that no longer exists would resequence nothing",
    });
});

test("allowDisconnected restores the drop for a row that left the DOM", () => {
    const { session, state, items } = makeSession(
        { allowDisconnected: true },
        buildHandlers("onDrop", "onDragEnd"),
    );
    session.willStartDrag(items[0]);
    state.dragging = true;
    items[0].remove();
    session.dragEnd(items[1]);
    expect.verifySteps(["build:onDrop", "build:onDragEnd"]);
});

test("a throwing caller handler tears the drag down before the error escapes", () => {
    const boom = new Error("caller exploded");
    const { session, state, ctx, items } = makeSession({
        onDrag: () => {
            throw boom;
        },
    });
    session.willStartDrag(items[0]);
    state.dragging = true;
    expect(() => session.callHandler("onDrag", {})).toThrow(boom.message);
    expect(state.dragging).toBe(false, {
        message: "an exception must not leave a drag mounted",
    });
    expect(ctx.current.element).toBe(/** @type {any} */ (undefined));
});

test("onKeyDown ends a drag on any key that is not a bare modifier", () => {
    const { session, state, items } = makeSession();
    session.willStartDrag(items[0]);
    state.dragging = true;

    session.onKeyDown(new KeyboardEvent("keydown", { key: "Shift", cancelable: true }));
    expect(state.dragging).toBe(true, { message: "a modifier alone is whitelisted" });

    session.onKeyDown(
        new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
    );
    expect(state.dragging).toBe(false);
});

test("onKeyDown is inert when nothing is being dragged", () => {
    const { session, state } = makeSession();
    const ev = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
    session.onKeyDown(ev);
    expect(state.dragging).toBe(false);
    expect.verifySteps([], { message: "no cleanup runs for a key with no drag" });
    expect(ev.defaultPrevented).toBe(false, {
        message: "a key nobody is dragging through must reach the rest of the page",
    });
});

test("onClick swallows the click that ends a drag, and only that one", () => {
    const { session, state, items } = makeSession();
    const before = pointer("click");
    session.onClick(before);
    expect(before.defaultPrevented).toBe(false, {
        message: "a click with no drag behind it must still activate the row",
    });

    session.willStartDrag(items[0]);
    state.dragging = true;
    session.dragEnd(items[0]);
    const after = pointer("click");
    session.onClick(after);
    expect(after.defaultPrevented).toBe(true);
});

test("onPointerMove is inert once the drag's ctx.current has been released", () => {
    const { session, items } = makeSession({ onDrag: () => expect.step("drag") });
    session.willStartDrag(items[0]);
    session.cleanup.cleanup();
    session.onPointerMove(pointer("pointermove", { clientX: 500, clientY: 500 }));
    expect.verifySteps([], { message: "a released drag cannot be resumed by a move" });
});

test("onPointerMove does not start a drag while enable() is false", () => {
    const { session, ctx, state, items } = makeSession({
        onDragStart: () => expect.step("start"),
    });
    session.willStartDrag(items[0]);
    ctx.enable = () => false;
    session.onPointerMove(pointer("pointermove", { clientX: 500, clientY: 500 }));
    expect.verifySteps([]);
    expect(state.dragging).toBe(false);
});

test("onPointerDown ignores a non-left button without arming anything", () => {
    const { session, state, root, items } = makeSession();
    root.addEventListener("pointerdown", session.onPointerDown);
    items[0].dispatchEvent(pointer("pointerdown", { button: 2 }));
    expect(state.willDrag).toBe(false);
    expect(state.dragging).toBe(false);
});

test("onPointerDown respects preventDrag", () => {
    const { session, ctx, state, root, items } = makeSession();
    ctx.preventDrag = () => true;
    root.addEventListener("pointerdown", session.onPointerDown);
    items[0].dispatchEvent(pointer("pointerdown"));
    expect(state.willDrag).toBe(false, {
        message: "preventDrag refuses the press before anything is armed",
    });
});

test("onPointerDown arms the drag for a left press on a matching element", () => {
    const { session, ctx, state, root, items } = makeSession();
    root.addEventListener("pointerdown", session.onPointerDown);
    items[1].dispatchEvent(pointer("pointerdown", { clientX: 10, clientY: 20 }));
    expect(state.willDrag).toBe(true);
    expect(ctx.current.element).toBe(items[1]);
    expect(ctx.current.initialPosition).toEqual({ x: 10, y: 20 });
});

test("onPointerDown ignores a press inside the ignore selector", () => {
    const { session, ctx, state, root, items } = makeSession();
    ctx.ignoreSelector = ".no-drag";
    const handle = document.createElement("span");
    handle.className = "no-drag";
    items[0].appendChild(handle);
    root.addEventListener("pointerdown", session.onPointerDown);
    handle.dispatchEvent(pointer("pointerdown"));
    expect(state.willDrag).toBe(false);
});
