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
    expect(writes[0]).toMatch(/^a=b; path=\/; max-age=\d+; SameSite=Lax$/);
});

test("set escapes the characters that corrupt the cookie string", () => {
    const writes = captureCookieWrites();
    // `;` would truncate the value; `%` would corrupt the read-side
    // decoding; control characters make the assignment a silent no-op.
    cookie.set("k", "a;b%c\nd");
    expect(writes[0]).toMatch(/^k=a%3Bb%25c%0Ad; /);
    // ...and get() reverses the escaping: the value round-trips.
    expect(cookie.get("k")).toBe("a;b%c\nd");
});

test("set leaves server-parsed raw values untouched", () => {
    // Several cookies are a cross-layer protocol whose raw value the server
    // parses as-is (e.g. the `website_cookies_bar` consent JSON, `cids`,
    // `frontend_lang`): spaces, commas, quotes, brackets must NOT be
    // percent-encoded.
    const writes = captureCookieWrites();
    const consent = '{"required": true, "optional": false, "ts": 123}';
    cookie.set("website_cookies_bar", consent);
    expect(writes[0].startsWith(`website_cookies_bar=${consent}; `)).toBe(true);
    expect(cookie.get("website_cookies_bar")).toBe(consent);
});

test("get returns legacy raw values with a bare % untouched", () => {
    // Cookies written before the escaping existed may contain a bare `%`
    // that is not a valid escape sequence: get() must not throw.
    let raw = "legacy=100%";
    patchWithCleanup(cookie, {
        get _cookieMonster() {
            return raw;
        },
        set _cookieMonster(value) {
            raw = value;
        },
    });
    expect(cookie.get("legacy")).toBe("100%");
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
