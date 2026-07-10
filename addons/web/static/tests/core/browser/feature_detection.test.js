// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    hasTouch,
    isAndroid,
    isAndroidApp,
    isBrowserChrome,
    isBrowserFirefox,
    isBrowserMicrosoftEdge,
    isBrowserSafari,
    isIOS,
    isIosApp,
    isMacOS,
    isMobileOS,
    isOtherMobileOS,
    maxTouchPoints,
} from "@web/core/browser/feature_detection";

describe.current.tags("headless");

// Helpers

const UA_CHROME_MAC =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const UA_FIREFOX_LINUX =
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0";
const UA_EDGE_WINDOWS =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0";
const UA_SAFARI_MAC =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15";
const UA_ANDROID_CHROME =
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
const UA_IPHONE =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const UA_IPAD_DESKTOP =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15";
const UA_ODOO_IOS =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) OdooMobile (iOS) Safari/604.1";
const UA_ODOO_ANDROID =
    "Mozilla/5.0 (Linux; Android 14) OdooMobile Chrome/120.0.0.0 Android Mobile Safari/537.36";
const UA_BLACKBERRY =
    "Mozilla/5.0 (BB10; Touch) AppleWebKit/537.10+ (KHTML, like Gecko) Version/10.0.9.2372 Mobile Safari/537.10+ BlackBerry";

/**
 * Patch browser.navigator with a specific user agent string.
 * @param {string} ua
 * @param {object} [extra] additional navigator properties
 */
function patchUA(ua, extra = {}) {
    patchWithCleanup(browser, {
        navigator: { userAgent: ua, maxTouchPoints: 0, ...extra },
    });
}

describe("isBrowserChrome", () => {
    test("detects Chrome on Mac", () => {
        patchUA(UA_CHROME_MAC);
        expect(isBrowserChrome()).toBe(true);
    });

    test("does not detect Chrome for Firefox", () => {
        patchUA(UA_FIREFOX_LINUX);
        expect(isBrowserChrome()).toBe(false);
    });

    test("detects Chrome for Edge (Chromium-based)", () => {
        patchUA(UA_EDGE_WINDOWS);
        expect(isBrowserChrome()).toBe(true);
    });

    test("does not detect Chrome for Safari", () => {
        patchUA(UA_SAFARI_MAC);
        expect(isBrowserChrome()).toBe(false);
    });
});

describe("isBrowserFirefox", () => {
    test("detects Firefox", () => {
        patchUA(UA_FIREFOX_LINUX);
        expect(isBrowserFirefox()).toBe(true);
    });

    test("does not detect Firefox for Chrome", () => {
        patchUA(UA_CHROME_MAC);
        expect(isBrowserFirefox()).toBe(false);
    });
});

describe("isBrowserMicrosoftEdge", () => {
    test("detects Edge", () => {
        patchUA(UA_EDGE_WINDOWS);
        expect(isBrowserMicrosoftEdge()).toBe(true);
    });

    test("does not detect Edge for Chrome", () => {
        patchUA(UA_CHROME_MAC);
        expect(isBrowserMicrosoftEdge()).toBe(false);
    });
});

describe("isBrowserSafari", () => {
    test("detects Safari (not Chrome-based)", () => {
        patchUA(UA_SAFARI_MAC);
        expect(isBrowserSafari()).toBe(true);
    });

    test("does not detect Safari for Chrome (has 'Safari' in UA)", () => {
        patchUA(UA_CHROME_MAC);
        // Chrome's UA contains "Safari" but isBrowserSafari should return false
        expect(isBrowserSafari()).toBe(false);
    });

    test("does not detect Safari for Firefox", () => {
        patchUA(UA_FIREFOX_LINUX);
        expect(isBrowserSafari()).toBe(false);
    });
});

describe("isMacOS", () => {
    test("detects macOS from Chrome UA", () => {
        patchUA(UA_CHROME_MAC);
        expect(isMacOS()).toBe(true);
    });

    test("detects macOS from Safari UA", () => {
        patchUA(UA_SAFARI_MAC);
        expect(isMacOS()).toBe(true);
    });

    test("does not detect macOS for Linux", () => {
        patchUA(UA_FIREFOX_LINUX);
        expect(isMacOS()).toBe(false);
    });

    test("does not detect macOS for Windows", () => {
        patchUA(UA_EDGE_WINDOWS);
        expect(isMacOS()).toBe(false);
    });
});

describe("isAndroid", () => {
    test("detects Android", () => {
        patchUA(UA_ANDROID_CHROME);
        expect(isAndroid()).toBe(true);
    });

    test("does not detect Android for desktop", () => {
        patchUA(UA_CHROME_MAC);
        expect(isAndroid()).toBe(false);
    });
});

describe("isIOS", () => {
    test("detects iPhone", () => {
        patchUA(UA_IPHONE);
        expect(isIOS()).toBe(true);
    });

    test("detects iPad in desktop mode via platform + touchpoints", () => {
        patchUA(UA_IPAD_DESKTOP, { platform: "MacIntel", maxTouchPoints: 5 });
        expect(isIOS()).toBe(true);
    });

    test("does not falsely detect macOS desktop as iOS", () => {
        patchUA(UA_SAFARI_MAC, { platform: "MacIntel", maxTouchPoints: 0 });
        expect(isIOS()).toBe(false);
    });

    test("does not detect iOS for Android", () => {
        patchUA(UA_ANDROID_CHROME);
        expect(isIOS()).toBe(false);
    });
});

describe("isMobileOS", () => {
    test("detects Android as mobile", () => {
        patchUA(UA_ANDROID_CHROME);
        expect(isMobileOS()).toBe(true);
    });

    test("detects iPhone as mobile", () => {
        patchUA(UA_IPHONE);
        expect(isMobileOS()).toBe(true);
    });

    test("detects BlackBerry as mobile", () => {
        patchUA(UA_BLACKBERRY);
        expect(isMobileOS()).toBe(true);
    });

    test("does not detect desktop as mobile", () => {
        patchUA(UA_CHROME_MAC);
        expect(isMobileOS()).toBe(false);
    });
});

describe("isOtherMobileOS", () => {
    test("detects BlackBerry", () => {
        patchUA(UA_BLACKBERRY);
        expect(isOtherMobileOS()).toBe(true);
    });

    test("does not detect Android as 'other' mobile", () => {
        patchUA(UA_ANDROID_CHROME);
        expect(isOtherMobileOS()).toBe(false);
    });
});

// Odoo mobile apps

describe("isIosApp", () => {
    test("detects Odoo iOS app", () => {
        patchUA(UA_ODOO_IOS);
        expect(isIosApp()).toBe(true);
    });

    test("does not detect regular iOS browser as app", () => {
        patchUA(UA_IPHONE);
        expect(isIosApp()).toBe(false);
    });
});

describe("isAndroidApp", () => {
    test("detects Odoo Android app", () => {
        patchUA(UA_ODOO_ANDROID);
        expect(isAndroidApp()).toBe(true);
    });

    test("does not detect regular Android browser as app", () => {
        patchUA(UA_ANDROID_CHROME);
        expect(isAndroidApp()).toBe(false);
    });
});

// Cache invalidation — critical for test isolation

describe("UA cache", () => {
    test("returns updated result when UA changes between calls", () => {
        patchUA(UA_CHROME_MAC);
        expect(isMacOS()).toBe(true);
        expect(isBrowserChrome()).toBe(true);

        // Simulate UA change (as happens when tests patch browser.navigator)
        patchUA(UA_FIREFOX_LINUX);
        expect(isMacOS()).toBe(false);
        expect(isBrowserChrome()).toBe(false);
        expect(isBrowserFirefox()).toBe(true);
    });

    test("cache is consistent across all functions for same UA", () => {
        patchUA(UA_EDGE_WINDOWS);
        expect(isBrowserChrome()).toBe(true); // Chromium-based
        expect(isBrowserMicrosoftEdge()).toBe(true);
        expect(isBrowserSafari()).toBe(false);
        expect(isBrowserFirefox()).toBe(false);
        expect(isMacOS()).toBe(false);
        expect(isAndroid()).toBe(false);
    });
});

// Touch / non-UA features (not cached — left as-is)

describe("hasTouch", () => {
    test("detects touch via ontouchstart", () => {
        patchWithCleanup(browser, { ontouchstart: () => {} });
        expect(hasTouch()).toBe(true);
    });
});

describe("maxTouchPoints", () => {
    test("returns navigator.maxTouchPoints", () => {
        patchWithCleanup(browser, {
            navigator: { ...browser.navigator, maxTouchPoints: 5 },
        });
        expect(maxTouchPoints()).toBe(5);
    });

    test("returns 0 when not available", () => {
        patchWithCleanup(browser, {
            navigator: { ...browser.navigator, maxTouchPoints: 0 },
        });
        expect(maxTouchPoints()).toBe(0);
    });
});
