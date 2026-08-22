// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import {
    getService,
    makeMockEnv,
    mockServiceWorkerRegistration,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");

/**
 * @param {{ controlled?: boolean, reply?: any }} [options]
 */
function mockServiceWorker({ controlled = true, reply } = {}) {
    const listeners = new Set();
    const serviceWorker = {
        register: async () => mockServiceWorkerRegistration(),
        ready: Promise.resolve(),
        controller: controlled
            ? {
                  postMessage(message) {
                      expect.step(`postMessage:${message}`);
                      if (reply === undefined) {
                          return;
                      }
                      for (const listener of [...listeners]) {
                          listener({ data: reply });
                      }
                  },
              }
            : null,
        addEventListener: (_type, listener) => listeners.add(listener),
        removeEventListener: (_type, listener) => listeners.delete(listener),
    };
    patchWithCleanup(browser, { navigator: { ...browser.navigator, serviceWorker } });
    return { listenerCount: () => listeners.size };
}

/** @param {string} search */
function mockLocation(search) {
    patchWithCleanup(browser, {
        location: {
            ...browser.location,
            href: `https://example.com/odoo${search}`,
            search,
        },
    });
}

/**
 * @param {{ onSelect?: () => any, apps?: Record<string, any>[], claims?: string[] }} [options]
 */
function mockExpensesApp({
    onSelect,
    apps = [{ actionPath: "expenses", id: 42 }],
    claims = ["expenses"],
} = {}) {
    const menu = {
        getApps: () => apps,
        selectMenu: async (app) => {
            expect.step(`selectMenu:${app.actionPath}`);
            if (onSelect) {
                await onSelect();
            }
        },
    };
    const services = registry.category("services");
    services.add("menu", { start: () => menu }, { force: true });
    after(() => services.remove("menu"));

    const shareTargets = registry.category("share_target_apps");
    claims.forEach((path, index) => shareTargets.add(`claim${index}`, path));
    after(() => claims.forEach((_, index) => shareTargets.remove(`claim${index}`)));
}

test("does nothing when the page was not opened from a share", async () => {
    mockLocation("");
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: [{}] },
    });
    mockExpensesApp();
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps([]);
    expect(getService("shareTarget").hasSharedFiles()).toBe(false);
});

test("an uncontrolled page yields no files and no navigation", async () => {
    mockLocation("?share_target=trigger");
    mockServiceWorker({ controlled: false });
    mockExpensesApp();
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps([]);
    expect(getService("shareTarget").hasSharedFiles()).toBe(false);
});

test("an acked share navigates to the expenses app and hands the files over once", async () => {
    mockLocation("?share_target=trigger");
    const files = [{ name: "receipt.png" }];
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: files },
    });
    mockExpensesApp();
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps(["postMessage:odoo_share_target", "selectMenu:expenses"]);
    const shareTarget = getService("shareTarget");
    expect(shareTarget.hasSharedFiles()).toBe(true);
    expect(shareTarget.getSharedFilesToUpload()).toBe(files);
    expect(shareTarget.getSharedFilesToUpload()).toBe(null);
    expect(shareTarget.hasSharedFiles()).toBe(false);
});

test("an empty share does not navigate", async () => {
    mockLocation("?share_target=trigger");
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: [] },
    });
    mockExpensesApp();
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps(["postMessage:odoo_share_target"]);
    expect(getService("shareTarget").hasSharedFiles()).toBe(false);
});

test("a worker that never acks gives up on the timeout and unhooks", async () => {
    mockLocation("?share_target=trigger");
    const sw = mockServiceWorker({ reply: undefined });
    mockExpensesApp();
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();
    expect.verifySteps(["postMessage:odoo_share_target"]);
    expect(sw.listenerCount()).toBe(1);

    await advanceTime(5000);
    await animationFrame();

    expect(getService("shareTarget").hasSharedFiles()).toBe(false);
    expect(sw.listenerCount()).toBe(0);
});

test("a rejecting navigation is contained, not left unhandled", async () => {
    mockLocation("?share_target=trigger");
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: [{ name: "a.png" }] },
    });
    mockExpensesApp({
        onSelect: () => Promise.reject(new Error("navigation failed")),
    });
    const env = await makeMockEnv();

    const unhandled = [];
    const onUnhandled = (ev) => {
        unhandled.push(ev.reason);
        ev.preventDefault();
    };
    window.addEventListener("unhandledrejection", onUnhandled);
    after(() => window.removeEventListener("unhandledrejection", onUnhandled));

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();
    await animationFrame();

    expect.verifySteps(["postMessage:odoo_share_target", "selectMenu:expenses"]);
    expect(unhandled).toHaveLength(0);
    expect(getService("shareTarget").hasSharedFiles()).toBe(true);
});

test("no app claims the share target: nothing is asked of the worker", async () => {
    mockLocation("?share_target=trigger");
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: [{}] },
    });
    mockExpensesApp({ claims: [] });
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps([]);
    expect(getService("shareTarget").hasSharedFiles()).toBe(false);
});

test("the first claim that matches an installed app wins", async () => {
    mockLocation("?share_target=trigger");
    mockServiceWorker({
        reply: { action: "odoo_share_target_ack", shared_files: [{ name: "a.png" }] },
    });
    mockExpensesApp({
        apps: [{ actionPath: "expenses", id: 42 }],
        claims: ["not-installed", "expenses"],
    });
    const env = await makeMockEnv();

    env.bus.trigger(AppEvent.WEB_CLIENT_READY);
    await animationFrame();

    expect.verifySteps(["postMessage:odoo_share_target", "selectMenu:expenses"]);
});
