// @ts-check

import { expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    executeActURLAction,
    openActionInNewWindow,
    openURL,
} from "@web/webclient/actions/action_executors/act_url";

/**
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    const calls = { notifications: [], doAction: [] };
    const am = {
        env: {},
        notificationService: {
            add: (message, options) => calls.notifications.push({ message, options }),
        },
        router: { stateToUrl: (state) => `/odoo/from-state/${state?.id ?? ""}` },
        doAction: async (action, options) => {
            calls.doAction.push({ action, options });
            return "doAction-result";
        },
        ...overrides,
    };
    am.__calls = calls;
    return am;
}

function patchBrowser({ openReturns = { closed: false } } = {}) {
    const calls = { open: [], assign: [] };
    patchWithCleanup(browser, {
        open: /** @type {any} */ (
            (url, target) => {
                calls.open.push({ url, target });
                return openReturns;
            }
        ),
    });
    patchWithCleanup(browser.location, {
        assign: (url) => calls.assign.push(url),
    });
    return calls;
}

test("an empty url is a no-op (never navigates to /undefined)", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    expect(await executeActURLAction(/** @type {any} */ ({ url: "" }), {}, am)).toBe(
        undefined,
    );
    expect(browserCalls.open).toEqual([]);
    expect(browserCalls.assign).toEqual([]);
});

test("a bare relative url gets a leading slash", async () => {
    const browserCalls = patchBrowser();
    await executeActURLAction(
        /** @type {any} */ ({ url: "my/report" }),
        {},
        makeFakeAm(),
    );
    expect(browserCalls.open.map((c) => c.url)).toEqual(["/my/report"]);
});

test("an absolute http url is passed through untouched", async () => {
    const browserCalls = patchBrowser();
    await executeActURLAction(
        /** @type {any} */ ({ url: "https://example.com/x?y=1" }),
        {},
        makeFakeAm(),
    );
    expect(browserCalls.open.map((c) => c.url)).toEqual(["https://example.com/x?y=1"]);
});

test("a bare javascript: url is blocked by the guard, not defused by the prefix", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    await executeActURLAction(
        /** @type {any} */ ({ url: "javascript:alert(1)" }),
        {},
        am,
    );
    expect(browserCalls.open).toEqual([]);
    expect(browserCalls.assign).toEqual([]);
    expect(am.__calls.notifications).toHaveLength(1);
    expect(am.__calls.notifications[0].options).toEqual({
        sticky: true,
        type: "danger",
    });
});

test("a protocol-relative //host url is blocked with a danger notification", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    await executeActURLAction(/** @type {any} */ ({ url: "//evil.example" }), {}, am);
    expect(browserCalls.open).toEqual([]);
    expect(browserCalls.assign).toEqual([]);
    expect(am.__calls.notifications).toHaveLength(1);
    expect(am.__calls.notifications[0].options).toEqual({
        sticky: true,
        type: "danger",
    });
});

test("an http-prefixed but unsafe scheme is blocked", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    await executeActURLAction(
        /** @type {any} */ ({ url: "httpjavascript:alert(1)" }),
        {},
        am,
    );
    expect(browserCalls.open).toEqual([]);
    expect(am.__calls.notifications).toHaveLength(1);
});

test('target "self" replaces the current page instead of opening a tab', async () => {
    const browserCalls = patchBrowser();
    await executeActURLAction(
        /** @type {any} */ ({ url: "/here", target: "self" }),
        {},
        makeFakeAm(),
    );
    expect(browserCalls.assign).toEqual(["/here"]);
    expect(browserCalls.open).toEqual([]);
});

test('target "download" opens a new tab and never chains a close', async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    await executeActURLAction(
        /** @type {any} */ ({ url: "/f.pdf", target: "download", close: true }),
        {},
        am,
    );
    expect(browserCalls.open.map((c) => c.url)).toEqual(["/f.pdf"]);
    expect(am.__calls.doAction).toEqual([]);
});

test("every path settles options.onClose — download", async () => {
    patchBrowser();
    let called = 0;
    await executeActURLAction(
        /** @type {any} */ ({ url: "/f.pdf", target: "download" }),
        { onClose: () => called++ },
        makeFakeAm(),
    );
    expect(called).toBe(1);
});

test("every path settles options.onClose — no url at all", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    let called = 0;
    await executeActURLAction(
        /** @type {any} */ ({ url: "" }),
        { onClose: () => called++ },
        am,
    );
    expect(called).toBe(1);
    expect(browserCalls.open).toEqual([]);
    expect(browserCalls.assign).toEqual([]);
    expect(am.__calls.notifications).toEqual([]);
});

test("every path settles options.onClose — blocked unsafe scheme", async () => {
    const browserCalls = patchBrowser();
    const am = makeFakeAm();
    let called = 0;
    await executeActURLAction(
        /** @type {any} */ ({ url: "httpjavascript:alert(1)" }),
        { onClose: () => called++ },
        am,
    );
    expect(called).toBe(1);
    expect(browserCalls.open).toEqual([]);
    expect(am.__calls.notifications).toHaveLength(1);
});

test("every path settles options.onClose — target self", async () => {
    const browserCalls = patchBrowser();
    let called = 0;
    await executeActURLAction(
        /** @type {any} */ ({ url: "/here", target: "self" }),
        { onClose: () => called++ },
        makeFakeAm(),
    );
    expect(browserCalls.assign).toEqual(["/here"]);
    expect(called).toBe(1);
});

test("default target with close:true chains an act_window_close carrying onClose", async () => {
    patchBrowser();
    const am = makeFakeAm();
    const onClose = () => {};
    const res = await executeActURLAction(
        /** @type {any} */ ({ url: "/x", close: true }),
        { onClose },
        am,
    );
    expect(am.__calls.doAction).toHaveLength(1);
    expect(am.__calls.doAction[0].action).toEqual({
        type: "ir.actions.act_window_close",
    });
    expect(am.__calls.doAction[0].options.onClose).toBe(onClose);
    expect(/** @type {any} */ (res)).toBe("doAction-result");
});

test("default target without close calls onClose directly", async () => {
    patchBrowser();
    const am = makeFakeAm();
    let called = 0;
    await executeActURLAction(
        /** @type {any} */ ({ url: "/x" }),
        { onClose: () => called++ },
        am,
    );
    expect(called).toBe(1);
    expect(am.__calls.doAction).toEqual([]);
});

test("openURL warns (sticky) when the popup is blocked — null window", async () => {
    patchBrowser({ openReturns: null });
    const am = makeFakeAm();
    openURL("/x", am);
    expect(am.__calls.notifications).toHaveLength(1);
    expect(am.__calls.notifications[0].options).toEqual({
        sticky: true,
        type: "warning",
    });
});

test("openURL warns when the popup is blocked — already-closed window", async () => {
    patchBrowser({ openReturns: { closed: true } });
    const am = makeFakeAm();
    openURL("/x", am);
    expect(am.__calls.notifications).toHaveLength(1);
});

test("openURL stays silent when the popup opens", async () => {
    patchBrowser({ openReturns: { closed: false } });
    const am = makeFakeAm();
    openURL("/x", am);
    expect(am.__calls.notifications).toEqual([]);
});

test("openActionInNewWindow opens the router url and restores sessionStorage", async () => {
    const browserCalls = patchBrowser();
    browser.sessionStorage.setItem("current_action", '{"id":"before"}');
    browser.sessionStorage.setItem("current_state", '{"s":"before"}');
    const am = makeFakeAm();

    openActionInNewWindow({ _originalAction: '{"id":42}' }, { id: 42 }, am);

    expect(browserCalls.open.map((c) => c.url)).toEqual(["/odoo/from-state/42"]);
    expect(browser.sessionStorage.getItem("current_action")).toBe('{"id":"before"}');
    expect(browser.sessionStorage.getItem("current_state")).toBe('{"s":"before"}');
});

test("openActionInNewWindow exposes the action to the new context while opening", async () => {
    let seenDuringOpen = { action: null, state: null };
    patchWithCleanup(browser, {
        open: /** @type {any} */ (
            () => {
                seenDuringOpen = {
                    action: browser.sessionStorage.getItem("current_action"),
                    state: browser.sessionStorage.getItem("current_state"),
                };
                return { closed: false };
            }
        ),
    });
    openActionInNewWindow({ _originalAction: '{"id":42}' }, { id: 42 }, makeFakeAm());
    expect(seenDuringOpen.action).toBe('{"id":42}');
    expect(JSON.parse(seenDuringOpen.state ?? "null")).toEqual({ id: 42 });
});
