// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { cookie } from "@web/core/browser/cookie";

describe.current.tags("headless");

/**
 * Captures the raw strings the cookie util writes to `document.cookie`, without
 * touching the real one.
 * @returns {string[]}
 */
function captureCookieWrites() {
    /** @type {string[]} */
    const writes = [];
    let raw = "";
    patchWithCleanup(cookie, {
        get _cookieMonster() {
            return raw;
        },
        set _cookieMonster(value) {
            writes.push(value);
            raw = value;
        },
    });
    return writes;
}

test("set writes a well-formed name=value cookie", () => {
    const writes = captureCookieWrites();
    cookie.set("a", "b");
    expect(writes.length).toBe(1);
    expect(writes[0]).toMatch(/^a=b; path=\/; max-age=\d+$/);
});

test("set(key, undefined) does not create an empty-named cookie", () => {
    const writes = captureCookieWrites();
    cookie.set("myKey", undefined);
    expect(writes.length).toBe(1);
    // Must NOT be the buggy name-only assignment `myKey; path=/…`, which the
    // browser parses as an empty-named cookie whose value is "myKey".
    expect(writes[0].startsWith("myKey;")).toBe(false);
    // Instead it deletes the properly-named cookie.
    expect(writes[0]).toMatch(/^myKey=; /);
    expect(writes[0]).toMatch(/max-age=0/);
});

test("delete removes the cookie by name", () => {
    const writes = captureCookieWrites();
    cookie.delete("myKey");
    expect(writes[0]).toMatch(/^myKey=; /);
    expect(writes[0]).toMatch(/max-age=0/);
});
