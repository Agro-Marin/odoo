import { multiTabService } from "@bus/multi_tab_service";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-dom";
import {
    makeMockEnv,
    patchWithCleanup,
    restoreRegistry,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

// `navigator.locks` is mocked per test by `mock_websocket.js`'s
// `setupWebSocketWorker` (run via the `MockServer.prototype.start` patch that
// `makeMockEnv` triggers), so these tests run against the deterministic
// in-memory lock manager, shared across the tabs they simulate.

// Ensure the real (locks-based) service is the registered one even if another
// suite swapped it.
registry.category("services").remove("multi_tab");
registry.category("services").add("multi_tab", multiTabService);
describe.current.tags("desktop");

test("the first tab is main, a second concurrent tab is not", async () => {
    const tab1 = await makeMockEnv();
    expect(await tab1.services.multi_tab.isOnMainTab()).toBe(true);
    restoreRegistry(registry);
    const tab2 = await makeMockEnv(null, { makeNew: true });
    expect(await tab2.services.multi_tab.isOnMainTab()).toBe(false);
});

test("election passes to the next tab on pagehide", async () => {
    const tab1 = await makeMockEnv();
    expect(await tab1.services.multi_tab.isOnMainTab()).toBe(true);
    // Prevent the second tab from receiving the pagehide event so only tab1
    // leaves.
    patchWithCleanup(browser, {
        addEventListener(eventName, callback) {
            if (eventName !== "pagehide") {
                super.addEventListener(eventName, callback);
            }
        },
    });
    restoreRegistry(registry);
    const tab2 = await makeMockEnv(null, { makeNew: true });
    expect(await tab2.services.multi_tab.isOnMainTab()).toBe(false);
    tab1.services.multi_tab.bus.addEventListener("no_longer_main_tab", () =>
        expect.step("tab1 no_longer_main_tab"),
    );
    tab2.services.multi_tab.bus.addEventListener("become_main_tab", () =>
        expect.step("tab2 become_main_tab"),
    );
    browser.dispatchEvent(new Event("pagehide"));
    await expect.waitForSteps(["tab1 no_longer_main_tab", "tab2 become_main_tab"]);
    expect(await tab1.services.multi_tab.isOnMainTab()).toBe(false);
    expect(await tab2.services.multi_tab.isOnMainTab()).toBe(true);
});

test("unregister() then a bfcache pageshow does NOT re-register", async () => {
    const env = await makeMockEnv();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
    env.services.multi_tab.unregister();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
    browser.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    await runAllTimers();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
});

test("pagehide then a bfcache pageshow re-registers the tab", async () => {
    const env = await makeMockEnv();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
    browser.dispatchEvent(new Event("pagehide"));
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
    browser.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    await runAllTimers();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
});

test("no split-brain: exactly one of many concurrent tabs is main", async () => {
    const tabs = [await makeMockEnv()];
    for (let i = 0; i < 3; i++) {
        restoreRegistry(registry);
        tabs.push(await makeMockEnv(null, { makeNew: true }));
    }
    const mainFlags = await Promise.all(
        tabs.map((t) => t.services.multi_tab.isOnMainTab()),
    );
    expect(mainFlags.filter(Boolean)).toHaveLength(1);
});
