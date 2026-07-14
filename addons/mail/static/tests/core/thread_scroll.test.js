import {
    AT_BOTTOM_THRESHOLD,
    computeSavedScrollTop,
    computeScrollAction,
    computeSmoothScrollTarget,
    isScrolledToBottom,
} from "@mail/core/common/thread_scroll_hook";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

/**
 * Headless tests of the thread scroll state machine arithmetic: no component
 * mount, no DOM — the decision logic and the snapshot math are pure functions.
 */

/** Baseline: 1000px of content in a 400px viewport → max scrollTop 600. */
function params(overrides = {}) {
    return {
        order: "asc",
        snapshot: undefined,
        scrollHeight: 1000,
        clientHeight: 400,
        olderMessagesLoaded: false,
        newerMessagesLoaded: false,
        hadLoadNewer: false,
        threadScrollTop: undefined,
        isHighlighting: false,
        lastSetValue: undefined,
        isSmoothScrolling: false,
        ...overrides,
    };
}

test("initial load scrolls to the present edge according to order", () => {
    // behavior 3/4: persisted "bottom" marker → present edge, per order
    expect(computeScrollAction(params({ threadScrollTop: "bottom" }))).toEqual({
        type: "restore",
        value: 600, // scrollHeight - clientHeight
        smooth: false,
    });
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: "bottom" })),
    ).toEqual({ type: "restore", value: 0, smooth: false });
});

test("initial load restores a numeric saved position according to order", () => {
    // behavior 4: saved positions are distances from the top edge in "asc"
    // order and from the bottom edge in "desc" order
    expect(computeScrollAction(params({ threadScrollTop: 150 }))).toEqual({
        type: "restore",
        value: 150,
        smooth: false,
    });
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: 150 })),
    ).toEqual({
        type: "restore",
        value: 450, // scrollHeight - saved - clientHeight
        smooth: false,
    });
});

test("no scroll to apply without a persisted position or during a highlight", () => {
    expect(computeScrollAction(params())).toEqual({ type: "none" });
    // behavior 5: highlighting takes priority over restoring
    expect(
        computeScrollAction(
            params({ threadScrollTop: "bottom", isHighlighting: true }),
        ),
    ).toEqual({ type: "none" });
});

test("loading older messages keeps the view in place (snapshot compensation)", () => {
    // behavior 2, content inserted above ("asc"): compensate the extra height
    const snapshot = { scrollTop: 100, scrollHeight: 700 };
    expect(
        computeScrollAction(params({ snapshot, olderMessagesLoaded: true })),
    ).toEqual({
        type: "snapshot-top",
        value: 400, // snapshot.scrollTop + newScrollHeight - snapshot.scrollHeight
    });
    // behavior 2, content inserted below ("desc"): same scrollTop keeps the
    // messages on screen in place
    expect(
        computeScrollAction(
            params({ order: "desc", snapshot, olderMessagesLoaded: true }),
        ),
    ).toEqual({ type: "snapshot-bottom", value: 100 });
});

test("loading newer messages keeps the view in place (snapshot compensation)", () => {
    const snapshot = { scrollTop: 250, scrollHeight: 700 };
    // "asc", not stuck to bottom: content inserted below → keep scrollTop
    expect(
        computeScrollAction(
            params({ snapshot, newerMessagesLoaded: true, threadScrollTop: 250 }),
        ),
    ).toEqual({ type: "snapshot-bottom", value: 250 });
    // "desc": newer messages are inserted above → compensate the extra height
    expect(
        computeScrollAction(
            params({ order: "desc", snapshot, newerMessagesLoaded: true }),
        ),
    ).toEqual({ type: "snapshot-top", value: 550 });
});

test("at bottom, newly arrived messages keep the view stuck to the bottom", () => {
    // behavior 3: at the bottom with everything loaded, new content must not
    // trigger the keep-in-place snapshot — the view sticks to the bottom
    const snapshot = { scrollTop: 300, scrollHeight: 700 };
    expect(
        computeScrollAction(
            params({ snapshot, newerMessagesLoaded: true, threadScrollTop: "bottom" }),
        ),
    ).toEqual({ type: "restore", value: 600, smooth: false });
    // ... unless newer messages could still be loaded at the previous render
    // (the "bottom" edge was not the present): then keep-in-place applies
    expect(
        computeScrollAction(
            params({
                snapshot,
                newerMessagesLoaded: true,
                threadScrollTop: "bottom",
                hadLoadNewer: true,
            }),
        ),
    ).toEqual({ type: "snapshot-bottom", value: 300 });
});

test("jump to present requests a smooth scroll to the present edge", () => {
    expect(computeScrollAction(params({ threadScrollTop: "bottom-smooth" }))).toEqual({
        type: "restore",
        value: 600,
        smooth: true,
    });
    expect(
        computeScrollAction(
            params({ order: "desc", threadScrollTop: "bottom-smooth" }),
        ),
    ).toEqual({ type: "restore", value: 0, smooth: true });
});

test("restore is suppressed while smooth scrolling or for a ±1px repeat", () => {
    // an in-flight smooth scroll must not be hijacked
    expect(
        computeScrollAction(
            params({ threadScrollTop: "bottom-smooth", isSmoothScrolling: true }),
        ),
    ).toEqual({ type: "none" });
    // re-setting (almost) the same value could override a concurrent user
    // scroll whose event did not register yet
    expect(
        computeScrollAction(params({ threadScrollTop: 150, lastSetValue: 150 })),
    ).toEqual({ type: "none" });
    expect(
        computeScrollAction(params({ threadScrollTop: 150, lastSetValue: 151 })),
    ).toEqual({ type: "none" });
    expect(
        computeScrollAction(params({ threadScrollTop: 150, lastSetValue: 152 })),
    ).toEqual({ type: "restore", value: 150, smooth: false });
});

test("at-bottom detection respects order, threshold and loadNewer", () => {
    const metrics = { scrollHeight: 1000, clientHeight: 400 };
    // "asc": within the threshold of the bottom edge
    expect(
        isScrolledToBottom({
            order: "asc",
            scrollTop: 600 - AT_BOTTOM_THRESHOLD + 1,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(true);
    expect(
        isScrolledToBottom({
            order: "asc",
            scrollTop: 600 - AT_BOTTOM_THRESHOLD,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(false);
    // "desc": the present edge is the top
    expect(
        isScrolledToBottom({
            order: "desc",
            scrollTop: AT_BOTTOM_THRESHOLD - 1,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(true);
    expect(
        isScrolledToBottom({
            order: "desc",
            scrollTop: AT_BOTTOM_THRESHOLD,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(false);
    // while newer messages can still be loaded, the bottom edge is not the
    // present: never "at bottom", even exactly on the edge
    expect(
        isScrolledToBottom({
            order: "asc",
            scrollTop: 600,
            loadNewer: true,
            ...metrics,
        }),
    ).toBe(false);
});

test("at-bottom detection without a scrollbar", () => {
    // content shorter than the viewport: scrollTop is pinned at 0 and the
    // view counts as at bottom in both orders
    const metrics = { scrollTop: 0, scrollHeight: 400, clientHeight: 400 };
    expect(isScrolledToBottom({ order: "asc", loadNewer: false, ...metrics })).toBe(
        true,
    );
    expect(isScrolledToBottom({ order: "desc", loadNewer: false, ...metrics })).toBe(
        true,
    );
});

test("saved scroll position round-trips through the restore math", () => {
    const metrics = { scrollHeight: 1000, clientHeight: 400 };
    expect(
        computeSavedScrollTop({
            order: "asc",
            scrollTop: 590,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe("bottom");
    expect(
        computeSavedScrollTop({
            order: "asc",
            scrollTop: 150,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(150);
    // "desc" saves the distance from the bottom edge...
    expect(
        computeSavedScrollTop({
            order: "desc",
            scrollTop: 450,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(150);
    // ... which the restore math maps back to the same scrollTop
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: 150 })),
    ).toEqual({ type: "restore", value: 450, smooth: false });
});

test("smooth scroll targets are clamped and no-ops are detected", () => {
    const metrics = { scrollHeight: 1000, clientHeight: 400 };
    // clamping to the reachable range
    expect(
        computeSmoothScrollTarget({ value: 9999999, scrollTop: 0, ...metrics }),
    ).toEqual({ target: 600, noMovement: false });
    expect(
        computeSmoothScrollTarget({ value: -50, scrollTop: 300, ...metrics }),
    ).toEqual({ target: 0, noMovement: false });
    // scrolling to (±1px of) the current position is a no-op: browsers never
    // fire "scrollend" for it, so callers must resolve immediately
    expect(
        computeSmoothScrollTarget({ value: 300.5, scrollTop: 300, ...metrics }),
    ).toEqual({ target: 300.5, noMovement: true });
    // without a scrollbar every target clamps to 0 → always a no-op
    expect(
        computeSmoothScrollTarget({
            value: 500,
            scrollTop: 0,
            scrollHeight: 400,
            clientHeight: 400,
        }),
    ).toEqual({ target: 0, noMovement: true });
});
