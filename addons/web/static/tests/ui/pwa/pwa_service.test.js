// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    mockService,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("headless");

const mountManifestLink = (href) => {
    const fixture = getFixture();
    const manifestLink = document.createElement("link");
    manifestLink.rel = "manifest";
    manifestLink.href = href;
    fixture.append(manifestLink);
};

test("PWA service fetches the manifest found in the page", async () => {
    await makeMockEnv();
    mountManifestLink("/web/manifest.webmanifest");
    onRpc("/*", (request) => {
        expect.step(new URL(request.url).pathname);
        return { name: "Odoo PWA" };
    });
    const pwaService = await getService("pwa");
    let appManifest = await pwaService.getManifest();
    expect(appManifest).toEqual({ name: "Odoo PWA" });
    expect.verifySteps(["/web/manifest.webmanifest"]);
    appManifest = await pwaService.getManifest();
    expect(appManifest).toEqual({ name: "Odoo PWA" });
    expect.verifySteps([]);
});

test("PWA installation process", async () => {
    const beforeInstallPromptEvent = new CustomEvent("beforeinstallprompt");
    beforeInstallPromptEvent.preventDefault = () => {};
    beforeInstallPromptEvent.prompt = async () => ({ outcome: "accepted" });
    browser.BeforeInstallPromptEvent = beforeInstallPromptEvent;
    await makeMockEnv();
    mountManifestLink("/web/manifest.scoped_app_manifest");
    onRpc("/*", (request) => {
        expect.step(new URL(request.url).pathname);
        return {
            name: "My App",
            scope: "/scoped_app/myApp",
            start_url: "/scoped_app/myApp",
        };
    });
    patchWithCleanup(browser.localStorage, {
        setItem(key, value) {
            if (key === "pwaService.installationState") {
                expect.step(value);
                return null;
            }
            return super.setItem(key, value);
        },
    });
    const pwaService = await getService("pwa");
    expect(pwaService.isAvailable).toBe(false);
    expect(pwaService.canPromptToInstall).toBe(false);
    browser.dispatchEvent(beforeInstallPromptEvent);
    expect(pwaService.isAvailable).toBe(true);
    expect(pwaService.canPromptToInstall).toBe(true);
    await pwaService.show({
        onDone: (res) => {
            expect.step("onDone call with installation " + res.outcome);
        },
    });
    expect(pwaService.canPromptToInstall).toBe(false);
    expect.verifySteps([
        '{"/odoo":"accepted"}',
        "onDone call with installation accepted",
    ]);
});

test("Safari install prompt: dismissal persists on every dialog close path", async () => {
    patchWithCleanup(browser, {
        navigator: {
            language: browser.navigator.language,
            userAgent:
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        },
    });
    mockService("dialog", {
        add(_component, _props, options) {
            expect.step("dialog opened");
            options.onClose();
            return () => {};
        },
    });
    await makeMockEnv();
    const pwaService = await getService("pwa");
    expect(pwaService.isAvailable).toBe(true);
    expect(pwaService.canPromptToInstall).toBe(true);

    await pwaService.show({
        onDone: () => expect.step("onDone"),
    });
    expect.verifySteps(["dialog opened", "onDone"]);
    expect(pwaService.canPromptToInstall).toBe(false);
    expect(
        JSON.parse(browser.localStorage.getItem("pwaService.installationState")),
    ).toEqual({ "/odoo": "dismissed" });
});

test("PWA service boots despite a corrupted installationState in localStorage", async () => {
    await makeMockEnv();
    browser.localStorage.setItem("pwaService.installationState", "{ not json");
    const pwaService = await getService("pwa");
    expect(typeof pwaService.getManifest).toBe("function");
    expect(pwaService.isAvailable).toBe(false);
});

test("a native prompt is consumed once, so a second show() cannot reject", async () => {
    let prompts = 0;
    const beforeInstallPromptEvent = new CustomEvent("beforeinstallprompt");
    beforeInstallPromptEvent.preventDefault = () => {};
    beforeInstallPromptEvent.prompt = async () => {
        if (++prompts > 1) {
            throw new DOMException("already prompted", "InvalidStateError");
        }
        return { outcome: "accepted" };
    };
    browser.BeforeInstallPromptEvent = beforeInstallPromptEvent;
    await makeMockEnv();
    const pwaService = await getService("pwa");
    browser.dispatchEvent(beforeInstallPromptEvent);

    await pwaService.show();
    await pwaService.show();
    expect(prompts).toBe(1);
});

test("concurrent getManifest() callers share a single fetch", async () => {
    await makeMockEnv();
    mountManifestLink("/web/manifest.webmanifest");
    let fetches = 0;
    onRpc("/*", () => {
        fetches++;
        return { name: "Odoo PWA" };
    });
    const pwaService = await getService("pwa");
    const [a, b, c] = await Promise.all([
        pwaService.getManifest(),
        pwaService.getManifest(),
        pwaService.getManifest(),
    ]);
    expect(fetches).toBe(1);
    expect(a).toEqual({ name: "Odoo PWA" });
    expect(b).toEqual(a);
    expect(c).toEqual(a);
});

test("a failed manifest fetch is retried rather than memoised forever", async () => {
    await makeMockEnv();
    mountManifestLink("/web/manifest.webmanifest");
    let attempts = 0;
    onRpc("/*", () => {
        if (++attempts === 1) {
            throw new Error("offline");
        }
        return { name: "Odoo PWA" };
    });
    const pwaService = await getService("pwa");
    await expect(pwaService.getManifest()).rejects.toThrow();
    expect(await pwaService.getManifest()).toEqual({ name: "Odoo PWA" });
    expect(attempts).toBe(2);
});

test("a native prompt that rejects leaves no install affordance behind", async () => {
    const beforeInstallPromptEvent = new Event("beforeinstallprompt");
    /** @type {any} */ (beforeInstallPromptEvent).prompt = () =>
        Promise.reject(new Error("prompt() may only be called once"));
    patchWithCleanup(browser, { BeforeInstallPromptEvent: Event });
    await makeMockEnv();
    const pwaService = await getService("pwa");
    browser.dispatchEvent(beforeInstallPromptEvent);
    expect(pwaService.canPromptToInstall).toBe(true);

    await expect(pwaService.show()).rejects.toThrow();

    // no prompt left, so nothing may claim one can still be shown
    expect(pwaService.nativePrompt).toBe(null);
    expect(pwaService.canPromptToInstall).toBe(false);
});
