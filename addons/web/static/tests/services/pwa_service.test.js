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
    // manifest is only fetched once to get the app name
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
    // Not mockUserAgent(): it appends the running browser's engine tokens
    // ("Chrome/..."), which defeats the Safari detection.
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
            // Simulate a dismissal that bypasses the explicit close button
            // (ESC, closeAll): the dialog service fires the onClose OPTION on
            // every removal path — the pwa service must wire it there.
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
    // A corrupted persisted value must not throw when parsed at service start,
    // otherwise pwa (and every service depending on it) fails on every boot.
    browser.localStorage.setItem("pwaService.installationState", "{ not json");
    const pwaService = await getService("pwa");
    // Service booted (start() ran to completion) despite the corrupted value.
    expect(typeof pwaService.getManifest).toBe("function");
    expect(pwaService.isAvailable).toBe(false);
});
