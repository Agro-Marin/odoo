// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    decideClickbotResume,
    RESUME_MAX_AGE_MS,
    resumeClickbotRun,
} from "@web/webclient/clickbot/clickbot_loader";
import { CLICKBOT_RUNNING_KEY } from "@web/webclient/clickbot/clickbot_state";

describe.current.tags("desktop");

const NOW = 1_000_000_000_000;

test("no saved run is not a resume", () => {
    expect(decideClickbotResume(null, NOW)).toEqual({ verdict: "none" });
    expect(decideClickbotResume("", NOW)).toEqual({ verdict: "none" });
});

test("a fresh saved run resumes, carrying its state", () => {
    const raw = JSON.stringify({ startedAt: NOW - 1000, xmlId: "base.menu_x" });
    const outcome = decideClickbotResume(raw, NOW);
    expect(outcome.verdict).toBe("resume");
    expect(outcome.state.xmlId).toBe("base.menu_x");
});

test("the staleness window is exactly RESUME_MAX_AGE_MS", () => {
    const at = (/** @type {number} */ age) =>
        decideClickbotResume(JSON.stringify({ startedAt: NOW - age }), NOW).verdict;
    expect(at(RESUME_MAX_AGE_MS)).toBe("resume");
    expect(at(RESUME_MAX_AGE_MS + 1)).toBe("stale");
});

test("a run with no usable startedAt is stale, not resumed forever", () => {
    for (const startedAt of [undefined, null, "yesterday", NaN, Infinity]) {
        expect(decideClickbotResume(JSON.stringify({ startedAt }), NOW).verdict).toBe(
            "stale",
        );
    }
});

test("a corrupt entry is reported as corrupt, not as a resume", () => {
    expect(decideClickbotResume("{not json", NOW)).toEqual({ verdict: "corrupt" });
    expect(decideClickbotResume("42", NOW)).toEqual({ verdict: "corrupt" });
    expect(decideClickbotResume("null", NOW)).toEqual({ verdict: "corrupt" });
});

test("a corrupt entry is cleared, so it cannot poison every later boot", () => {
    /** @type {string[]} */
    const removed = [];
    patchWithCleanup(browser.localStorage, {
        getItem: (/** @type {string} */ key) =>
            key === CLICKBOT_RUNNING_KEY ? "{not json" : null,
        removeItem: (/** @type {string} */ key) => removed.push(key),
    });
    expect(resumeClickbotRun({ now: NOW }).verdict).toBe("corrupt");
    expect(removed).toEqual([CLICKBOT_RUNNING_KEY]);
});

test("a stale entry is cleared rather than resumed", () => {
    /** @type {string[]} */
    const removed = [];
    patchWithCleanup(browser.localStorage, {
        getItem: (/** @type {string} */ key) =>
            key === CLICKBOT_RUNNING_KEY
                ? JSON.stringify({ startedAt: NOW - RESUME_MAX_AGE_MS - 1 })
                : null,
        removeItem: (/** @type {string} */ key) => removed.push(key),
    });
    expect(resumeClickbotRun({ now: NOW }).verdict).toBe("stale");
    expect(removed).toEqual([CLICKBOT_RUNNING_KEY]);
});

test("nothing saved touches storage at all", () => {
    /** @type {string[]} */
    const removed = [];
    patchWithCleanup(browser.localStorage, {
        getItem: () => null,
        removeItem: (/** @type {string} */ key) => removed.push(key),
    });
    expect(resumeClickbotRun({ now: NOW }).verdict).toBe("none");
    expect(removed).toEqual([]);
});
