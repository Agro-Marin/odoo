import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");
defineMailModels();

const KEY = "mail.html_composer.enabled";

function emitSharedValueUpdate(env, newValue) {
    env.services.legacy_multi_tab.bus.trigger("shared_value_updated", {
        key: KEY,
        newValue,
    });
}

function writeRawSharedValue(env, raw) {
    browser.localStorage.setItem(
        env.services.legacy_multi_tab.generateLocalStorageKey(KEY),
        raw,
    );
}

test("cross-tab update: a garbage stored value does not throw in the bus listener", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    writeRawSharedValue(env, "not json");
    emitSharedValueUpdate(env, "not json");
    expect(composer.htmlEnabled).toBe(false);
});

test("cross-tab update: removal reads back as a boolean, not null", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    env.services.legacy_multi_tab.setSharedValue(KEY, true);
    emitSharedValueUpdate(env, "true");
    expect(composer.htmlEnabled).toBe(true);
    env.services.legacy_multi_tab.removeSharedValue(KEY);
    emitSharedValueUpdate(env, null);
    expect(composer.htmlEnabled).toBe(false);
});

test("cross-tab update: a normal toggle from another tab is applied", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    expect(composer.htmlEnabled).toBe(false);
    env.services.legacy_multi_tab.setSharedValue(KEY, true);
    emitSharedValueUpdate(env, "true");
    expect(composer.htmlEnabled).toBe(true);
    env.services.legacy_multi_tab.setSharedValue(KEY, false);
    emitSharedValueUpdate(env, "false");
    expect(composer.htmlEnabled).toBe(false);
});

test("the cross-tab listener agrees with the startup reader on every raw value", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    for (const raw of [
        "true",
        "false",
        "not json",
        "undefined",
        "null",
        "0",
        '"yes"',
    ]) {
        writeRawSharedValue(env, raw);
        const asStartupWouldRead =
            env.services.legacy_multi_tab.getSharedValue(KEY, false) === true;
        emitSharedValueUpdate(env, raw);
        expect(composer.htmlEnabled).toBe(asStartupWouldRead);
        expect(composer.htmlEnabled).toBe(raw === "true");
    }
});
