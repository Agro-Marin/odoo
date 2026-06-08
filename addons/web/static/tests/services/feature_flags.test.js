// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    _resetFeatureFlagsCache,
    clearFeatureFlag,
    featureFlag,
    getFeatureFlagsSnapshot,
    setFeatureFlag,
} from "@web/services/feature_flags";
import { session } from "@web/session";

describe.current.tags("headless");

// Stable bag of LS keys we own, so tests don't leak fakes into the shared
// storage backend across cases.
const TEST_LS_KEYS = [
    "feature.test_bool",
    "feature.test_str",
    "feature.test_num",
    "feature.test_null",
    "feature.test_falsy_value",
];

beforeEach(() => {
    // Force the URL cache to be re-read on the next featureFlag() call;
    // each test stubs window.location.href independently.
    _resetFeatureFlagsCache();
    for (const k of TEST_LS_KEYS) {
        try {
            browser.localStorage.removeItem(k);
        } catch {
            // ignore
        }
    }
    // Wipe any server flags planted by a previous test. We intentionally
    // mutate session here — the snapshot is held by reference in the
    // module under test and is otherwise read-only at runtime.
    delete session.feature_flags;
});

function _stubLocation(href) {
    patchWithCleanup(browser, {
        location: { ...browser.location, href },
    });
    _resetFeatureFlagsCache();
}

test("default value when no source provides one", () => {
    expect(featureFlag("missing_flag")).toBe(false);
    expect(featureFlag("missing_flag", { default: true })).toBe(true);
    expect(featureFlag("missing_flag", { default: 42 })).toBe(42);
    expect(featureFlag("missing_flag", { default: "hello" })).toBe("hello");
});

test("server-supplied flag via session.feature_flags", () => {
    session.feature_flags = { perf_marks: true, retry_budget: 3 };
    expect(featureFlag("perf_marks")).toBe(true);
    expect(featureFlag("retry_budget")).toBe(3);
    expect(featureFlag("perf_marks", { default: false })).toBe(true);
});

test("localStorage overrides server", () => {
    session.feature_flags = { test_bool: false };
    setFeatureFlag("test_bool", true);
    expect(featureFlag("test_bool")).toBe(true);
});

test("localStorage value is parsed for type", () => {
    setFeatureFlag("test_bool", true);
    setFeatureFlag("test_str", "abc");
    setFeatureFlag("test_num", 7);
    setFeatureFlag("test_null", null);
    expect(featureFlag("test_bool")).toBe(true);
    expect(featureFlag("test_str")).toBe("abc");
    expect(featureFlag("test_num")).toBe(7);
    expect(featureFlag("test_null")).toBe(null);
});

test("URL ?features overrides everything", () => {
    session.feature_flags = { url_wins: false };
    setFeatureFlag("url_wins", false);
    _stubLocation("https://example.com/odoo?features=url_wins");
    expect(featureFlag("url_wins")).toBe(true);
});

test("URL accepts comma-separated entries with mixed shapes", () => {
    _stubLocation(
        "https://example.com/odoo?features=enabled,-disabled,counter:5,label:hello",
    );
    expect(featureFlag("enabled")).toBe(true);
    expect(featureFlag("disabled")).toBe(false);
    expect(featureFlag("counter")).toBe(5);
    expect(featureFlag("label")).toBe("hello");
});

test("URL ; separator works too", () => {
    _stubLocation("https://example.com/odoo?features=a:1;b:2");
    expect(featureFlag("a")).toBe(1);
    expect(featureFlag("b")).toBe(2);
});

test("URL bare 'name:' is treated as truthy", () => {
    _stubLocation("https://example.com/odoo?features=naked:");
    expect(featureFlag("naked")).toBe(true);
});

test("falsy localStorage values still beat server defaults", () => {
    session.feature_flags = { test_falsy_value: true };
    setFeatureFlag("test_falsy_value", false);
    expect(featureFlag("test_falsy_value")).toBe(false);
});

test("clearFeatureFlag falls back through the cascade", () => {
    session.feature_flags = { test_bool: true };
    setFeatureFlag("test_bool", false);
    expect(featureFlag("test_bool")).toBe(false);
    clearFeatureFlag("test_bool");
    expect(featureFlag("test_bool")).toBe(true);
});

test("getFeatureFlagsSnapshot reports sources correctly", () => {
    session.feature_flags = { from_server: "yes" };
    setFeatureFlag("test_str", "ls_value");
    _stubLocation("https://example.com/odoo?features=test_bool:true");
    const snap = getFeatureFlagsSnapshot();
    const byName = Object.fromEntries(snap.map((e) => [e.name, e]));
    expect(byName.test_bool.source).toBe("url");
    expect(byName.test_bool.value).toBe(true);
    expect(byName.test_str.source).toBe("localStorage");
    expect(byName.test_str.value).toBe("ls_value");
    expect(byName.from_server.source).toBe("server");
    expect(byName.from_server.value).toBe("yes");
});

test("URL entry overrides matching LS and server in the snapshot", () => {
    session.feature_flags = { test_bool: false };
    setFeatureFlag("test_bool", false);
    _stubLocation("https://example.com/odoo?features=test_bool:true");
    const snap = getFeatureFlagsSnapshot();
    const entry = snap.find((e) => e.name === "test_bool");
    expect(entry.source).toBe("url");
    expect(entry.value).toBe(true);
});
