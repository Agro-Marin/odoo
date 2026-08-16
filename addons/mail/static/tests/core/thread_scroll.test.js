import {
    AT_BOTTOM_THRESHOLD,
    computeSavedScrollTop,
    computeScrollAction,
    computeSmoothScrollTarget,
    isScrolledToBottom,
} from "@mail/core/common/thread_scroll_hook";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

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
    expect(computeScrollAction(params({ threadScrollTop: "bottom" }))).toEqual({
        type: "restore",
        value: 600,
        smooth: false,
    });
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: "bottom" })),
    ).toEqual({ type: "restore", value: 0, smooth: false });
});

test("initial load restores a numeric saved position according to order", () => {
    expect(computeScrollAction(params({ threadScrollTop: 150 }))).toEqual({
        type: "restore",
        value: 150,
        smooth: false,
    });
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: 150 })),
    ).toEqual({
        type: "restore",
        value: 450,
        smooth: false,
    });
});

test("no scroll to apply without a persisted position or during a highlight", () => {
    expect(computeScrollAction(params())).toEqual({ type: "none" });
    expect(
        computeScrollAction(
            params({ threadScrollTop: "bottom", isHighlighting: true }),
        ),
    ).toEqual({ type: "none" });
});

test("loading older messages keeps the view in place (snapshot compensation)", () => {
    const snapshot = { scrollTop: 100, scrollHeight: 700 };
    expect(
        computeScrollAction(params({ snapshot, olderMessagesLoaded: true })),
    ).toEqual({
        type: "snapshot-top",
        value: 400,
    });
    expect(
        computeScrollAction(
            params({ order: "desc", snapshot, olderMessagesLoaded: true }),
        ),
    ).toEqual({ type: "snapshot-bottom", value: 100 });
});

test("loading newer messages keeps the view in place (snapshot compensation)", () => {
    const snapshot = { scrollTop: 250, scrollHeight: 700 };
    expect(
        computeScrollAction(
            params({ snapshot, newerMessagesLoaded: true, threadScrollTop: 250 }),
        ),
    ).toEqual({ type: "snapshot-bottom", value: 250 });
    expect(
        computeScrollAction(
            params({ order: "desc", snapshot, newerMessagesLoaded: true }),
        ),
    ).toEqual({ type: "snapshot-top", value: 550 });
});

test("at bottom, newly arrived messages keep the view stuck to the bottom", () => {
    const snapshot = { scrollTop: 300, scrollHeight: 700 };
    expect(
        computeScrollAction(
            params({ snapshot, newerMessagesLoaded: true, threadScrollTop: "bottom" }),
        ),
    ).toEqual({ type: "restore", value: 600, smooth: false });
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
    expect(
        computeScrollAction(
            params({ threadScrollTop: "bottom-smooth", isSmoothScrolling: true }),
        ),
    ).toEqual({ type: "none" });
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
    expect(
        computeSavedScrollTop({
            order: "desc",
            scrollTop: 450,
            loadNewer: false,
            ...metrics,
        }),
    ).toBe(150);
    expect(
        computeScrollAction(params({ order: "desc", threadScrollTop: 150 })),
    ).toEqual({ type: "restore", value: 450, smooth: false });
});

test("smooth scroll targets are clamped and no-ops are detected", () => {
    const metrics = { scrollHeight: 1000, clientHeight: 400 };
    expect(
        computeSmoothScrollTarget({ value: 9999999, scrollTop: 0, ...metrics }),
    ).toEqual({ target: 600, noMovement: false });
    expect(
        computeSmoothScrollTarget({ value: -50, scrollTop: 300, ...metrics }),
    ).toEqual({ target: 0, noMovement: false });
    expect(
        computeSmoothScrollTarget({ value: 300.5, scrollTop: 300, ...metrics }),
    ).toEqual({ target: 300.5, noMovement: true });
    expect(
        computeSmoothScrollTarget({
            value: 500,
            scrollTop: 0,
            scrollHeight: 400,
            clientHeight: 400,
        }),
    ).toEqual({ target: 0, noMovement: true });
});
