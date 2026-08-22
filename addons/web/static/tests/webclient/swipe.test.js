// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    SWIPE_ACTIVATION_THRESHOLD,
    SWIPE_LEFT,
    SWIPE_RIGHT,
    SwipeTracker,
} from "@web/webclient/swipe";

/**
 * @param {number} clientX
 */
function touchAt(clientX) {
    return /** @type {any} */ ({ changedTouches: [{ clientX }] });
}

describe.current.tags("desktop");

test("a left-dismissing tracker fires on a long enough leftward swipe", () => {
    const swipe = new SwipeTracker(SWIPE_LEFT);
    swipe.start(touchAt(300));
    expect(swipe.end(touchAt(300 - SWIPE_ACTIVATION_THRESHOLD))).toBe(true);
});

test("a left-dismissing tracker ignores a rightward swipe", () => {
    const swipe = new SwipeTracker(SWIPE_LEFT);
    swipe.start(touchAt(0));
    expect(swipe.end(touchAt(500))).toBe(false);
});

test("a right-dismissing tracker fires on a long enough rightward swipe", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(10));
    expect(swipe.end(touchAt(10 + SWIPE_ACTIVATION_THRESHOLD))).toBe(true);
});

test("a right-dismissing tracker ignores a leftward swipe", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(500));
    expect(swipe.end(touchAt(0))).toBe(false);
});

test("travel exactly at the threshold dismisses", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(0));
    expect(swipe.end(touchAt(SWIPE_ACTIVATION_THRESHOLD))).toBe(true);
});

test("travel one pixel short of the threshold does not", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(0));
    expect(swipe.end(touchAt(SWIPE_ACTIVATION_THRESHOLD - 1))).toBe(false);
});

test("a gesture started at x=0 is a real gesture", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(0));
    expect(swipe.end(touchAt(400))).toBe(true);
});

test("ending without starting is not a gesture", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    expect(swipe.end(touchAt(400))).toBe(false);
});

test("a gesture cannot be consumed twice", () => {
    const swipe = new SwipeTracker(SWIPE_RIGHT);
    swipe.start(touchAt(0));
    expect(swipe.end(touchAt(400))).toBe(true);
    expect(swipe.end(touchAt(400))).toBe(false);
});
