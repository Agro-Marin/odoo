import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");
defineMailModels();

const KEY = "mail.html_composer.enabled";

/**
 * The cross-tab payload as `legacy_multi_tab` actually emits it: `newValue` is
 * the RAW localStorage string, never a parsed value, and `null` on removal.
 */
function emitSharedValueUpdate(env, newValue) {
    env.services.legacy_multi_tab.bus.trigger("shared_value_updated", {
        key: KEY,
        newValue,
    });
}

/** Write under the shared key the way a foreign/legacy writer would. */
function writeRawSharedValue(env, raw) {
    browser.localStorage.setItem(
        env.services.legacy_multi_tab.generateLocalStorageKey(KEY),
        raw,
    );
}

test("cross-tab update: a garbage stored value does not throw in the bus listener", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    // Another writer (the legacy-prefix migration, an extension, a manual
    // setItem) left a non-JSON value under the shared key.
    writeRawSharedValue(env, "not json");
    // A bare `JSON.parse(detail.newValue)` threw here, and an exception in one
    // listener of a synchronous EventBus dispatch skips the ones after it.
    emitSharedValueUpdate(env, "not json");
    // an unparseable value is not a preference: fall back to the default
    expect(composer.htmlEnabled).toBe(false);
});

test("cross-tab update: removal reads back as a boolean, not null", async () => {
    const env = await makeMockEnv();
    const composer = env.services["mail.composer"];
    env.services.legacy_multi_tab.setSharedValue(KEY, true);
    emitSharedValueUpdate(env, "true");
    expect(composer.htmlEnabled).toBe(true);
    // `removeSharedValue` fires a storage event whose newValue is null;
    // `JSON.parse(null)` is `null`, so the flag used to leave its boolean type
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
    // The defect was a disagreement between the two readers of one key: the
    // startup read tolerates whatever localStorage holds, the listener parsed
    // it bare. Pin them together over the values the key can actually carry.
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
        // what the startup path would compute for this stored value
        const asStartupWouldRead =
            env.services.legacy_multi_tab.getSharedValue(KEY, false) === true;
        emitSharedValueUpdate(env, raw);
        expect(composer.htmlEnabled).toBe(asStartupWouldRead);
        // and only a real stored `true` enables it
        expect(composer.htmlEnabled).toBe(raw === "true");
    }
});
