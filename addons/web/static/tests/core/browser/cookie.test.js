// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { cookie } from "@web/core/browser/cookie";

describe.current.tags("headless");

/**
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
    cookie.set("k", "a;b%c\nd");
    expect(writes[0]).toMatch(/^k=a%3Bb%25c%0Ad; /);
    expect(cookie.get("k")).toBe("a;b%c\nd");
});

test("set leaves server-parsed raw values untouched", () => {
    const writes = captureCookieWrites();
    const consent = '{"required": true, "optional": false, "ts": 123}';
    cookie.set("website_cookies_bar", consent);
    expect(writes[0].startsWith(`website_cookies_bar=${consent}; `)).toBe(true);
    expect(cookie.get("website_cookies_bar")).toBe(consent);
});

test("get returns legacy raw values with a bare % untouched", () => {
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
    expect(writes[0].startsWith("myKey;")).toBe(false);
    expect(writes[0]).toMatch(/^myKey=; /);
    expect(writes[0]).toMatch(/max-age=0/);
});

test("delete removes the cookie by name", () => {
    const writes = captureCookieWrites();
    cookie.delete("myKey");
    expect(writes[0]).toMatch(/^myKey=; /);
    expect(writes[0]).toMatch(/max-age=0/);
});

test("set escapes the characters that let a key smuggle cookie syntax", () => {
    const writes = captureCookieWrites();
    cookie.set("a=b", "c");
    expect(writes[0].startsWith("a%3Db=c; ")).toBe(true);
    expect(cookie.get("a=b")).toBe("c");
    expect(cookie.get("a")).toBe(undefined);
});

test("a key carrying an attribute separator cannot reach the attribute list", () => {
    const writes = captureCookieWrites();
    cookie.set("victim; Max-Age=0", "v");
    expect(writes[0]).toMatch(
        /^victim%3B%20Max-Age%3D0=v; path=\/; max-age=\d+; SameSite=Lax$/,
    );
    expect(writes[0].split("; ").length).toBe(4);
});

test("keys round-trip through get()", () => {
    captureCookieWrites();
    for (const key of ["plain", "a=b", "a;b", "a b", "a,b", "a%b"]) {
        cookie.set(key, "value");
        expect(cookie.get(key)).toBe("value", {
            message: `key ${JSON.stringify(key)}`,
        });
    }
});

describe("against the real document.cookie jar", () => {
    test("delete really removes the entry", () => {
        cookie.set("gone", "here");
        expect(cookie.get("gone")).toBe("here");
        cookie.delete("gone");
        expect(cookie.get("gone")).toBe(undefined);
        expect(document.cookie).not.toInclude("gone");
    });

    test("cookie attributes are not stored as cookies", () => {
        cookie.set("real", "1");
        expect(document.cookie).toInclude("real=1");
        for (const attribute of ["path", "max-age", "SameSite"]) {
            expect(cookie.get(attribute)).toBe(undefined, {
                message: `${attribute} must not become a cookie`,
            });
        }
        cookie.delete("real");
    });

    test("values survive the round trip whatever they contain", () => {
        for (const value of ["a=b", "a b", "a,b", "a;b", "a%b", 'a"b', "1=2=3"]) {
            cookie.set("probe", value);
            expect(cookie.get("probe")).toBe(value, {
                message: `value ${JSON.stringify(value)}`,
            });
        }
        cookie.delete("probe");
    });

    test("writing a cookie leaves its neighbours alone", () => {
        cookie.set("first", "1");
        cookie.set("second", "2");
        expect([cookie.get("first"), cookie.get("second")]).toEqual(["1", "2"]);
        cookie.delete("first");
        expect([cookie.get("first"), cookie.get("second")]).toEqual([undefined, "2"]);
        cookie.delete("second");
    });
});
