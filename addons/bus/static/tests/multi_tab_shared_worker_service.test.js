import { multiTabSharedWorkerService } from "@bus/multi_tab_shared_worker_service";
import { WORKER_STATE, WorkerService } from "@bus/services/worker_service";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-dom";
import {
    makeMockEnv,
    patchWithCleanup,
    restoreRegistry,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

registry.category("services").remove("multi_tab");
registry.category("services").add("multi_tab", multiTabSharedWorkerService);
describe.current.tags("desktop");

test("main tab service(election worker) elects new main on pagehide", async () => {
    const firstTabEnv = await makeMockEnv();
    expect(await firstTabEnv.services.multi_tab.isOnMainTab()).toBe(true);
    // Prevent second tab from receiving pagehide event.
    patchWithCleanup(browser, {
        addEventListener(eventName, callback) {
            if (eventName !== "pagehide") {
                super.addEventListener(eventName, callback);
            }
        },
    });
    restoreRegistry(registry);
    const secondTabEnv = await makeMockEnv(null, { makeNew: true });
    expect(await secondTabEnv.services.multi_tab.isOnMainTab()).toBe(false);
    firstTabEnv.services.multi_tab.bus.addEventListener("become_main_tab", () =>
        expect.step("tab1 become_main_tab"),
    );
    firstTabEnv.services.multi_tab.bus.addEventListener("no_longer_main_tab", () =>
        expect.step("tab1 no_longer_main_tab"),
    );
    secondTabEnv.services.multi_tab.bus.addEventListener("no_longer_main_tab", () =>
        expect.step("tab2 no_longer_main_tab"),
    );
    secondTabEnv.services.multi_tab.bus.addEventListener("become_main_tab", () =>
        expect.step("tab2 become_main_tab"),
    );
    browser.dispatchEvent(new Event("pagehide"));

    await expect.waitForSteps(["tab1 no_longer_main_tab", "tab2 become_main_tab"]);
    expect(await firstTabEnv.services.multi_tab.isOnMainTab()).toBe(false);
    expect(await secondTabEnv.services.multi_tab.isOnMainTab()).toBe(true);
});

test("J3: a failed worker makes isOnMainTab resolve false without hanging (shared)", async () => {
    patchWithCleanup(WorkerService.prototype, {
        async ensureWorkerStarted() {
            this._state = WORKER_STATE.FAILED;
            this.connectionInitializedDeferred.resolve();
        },
    });
    patchWithCleanup(console, { warn: () => {} });
    const env = await makeMockEnv();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
});

test("J3: unregister() then a bfcache pageshow does NOT re-register (shared)", async () => {
    const env = await makeMockEnv();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
    // Terminal unregistration: the tab permanently gives up main-tab duties.
    env.services.multi_tab.unregister();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
    // A bfcache restore must NOT resurrect a terminated tab.
    browser.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    await runAllTimers();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(false);
});

test("J3: pagehide then pageshow re-registers the tab (shared)", async () => {
    const env = await makeMockEnv();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
    // Transient unregistration on pagehide, re-registration on bfcache restore.
    browser.dispatchEvent(new Event("pagehide"));
    browser.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    await runAllTimers();
    expect(await env.services.multi_tab.isOnMainTab()).toBe(true);
});

test("main tab service(election worker) elects new main after unregister main tab", async () => {
    const firstTabEnv = await makeMockEnv();
    expect(await firstTabEnv.services.multi_tab.isOnMainTab()).toBe(true);
    restoreRegistry(registry);
    const secondTabEnv = await makeMockEnv(null, { makeNew: true });
    expect(await secondTabEnv.services.multi_tab.isOnMainTab()).toBe(false);
    firstTabEnv.services.multi_tab.bus.addEventListener("become_main_tab", () =>
        expect.step("tab1 become_main_tab"),
    );
    firstTabEnv.services.multi_tab.bus.addEventListener("no_longer_main_tab", () =>
        expect.step("tab1 no_longer_main_tab"),
    );
    secondTabEnv.services.multi_tab.bus.addEventListener("no_longer_main_tab", () =>
        expect.step("tab2 no_longer_main_tab"),
    );
    secondTabEnv.services.multi_tab.bus.addEventListener("become_main_tab", () =>
        expect.step("tab2 become_main_tab"),
    );
    firstTabEnv.services.multi_tab.unregister();

    await expect.waitForSteps(["tab1 no_longer_main_tab", "tab2 become_main_tab"]);
    expect(await firstTabEnv.services.multi_tab.isOnMainTab()).toBe(false);
    expect(await secondTabEnv.services.multi_tab.isOnMainTab()).toBe(true);
});
