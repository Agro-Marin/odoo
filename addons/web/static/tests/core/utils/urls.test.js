// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    compareUrls,
    getDataURLFromFile,
    getOrigin,
    imageUrl,
    redirect,
    url,
} from "@web/core/utils/urls";

describe.current.tags("headless");

beforeEach(() => {
    patchWithCleanup(browser, {
        location: { protocol: "http:", host: "testhost" },
    });
});

test("getOrigin", () => {
    expect(getOrigin()).toBe("http://testhost");
    expect(getOrigin("protocol://host")).toBe("protocol://host");
});

test("can return current origin", () => {
    patchWithCleanup(browser, {
        location: { protocol: "testprotocol:", host: "testhost" },
    });
    expect(url()).toBe("testprotocol://testhost");
});

test("can return custom origin", () => {
    const testUrl = url(null, null, { origin: "customProtocol://customHost/" });
    expect(testUrl).toBe("customProtocol://customHost");
});

test("can return custom origin with route", () => {
    const testUrl = url("/my_route", null, { origin: "customProtocol://customHost/" });
    expect(testUrl).toBe("customProtocol://customHost/my_route");
});

test("can return full route", () => {
    const testUrl = url("/my_route");
    expect(testUrl).toBe("http://testhost/my_route");
});

test("can return full route with params", () => {
    const testUrl = url("/my_route", { my_param: [1, 2], other: 9 });
    expect(testUrl).toBe("http://testhost/my_route?my_param=1%2C2&other=9");
});

test("can return cors urls", () => {
    const testUrl = url("https://cors_server/cors_route/");
    expect(testUrl).toBe("https://cors_server/cors_route/");
});

test("can be used for cors urls", () => {
    const testUrl = url("https://cors_server/cors_route/", { my_param: [1, 2] });
    expect(testUrl).toBe("https://cors_server/cors_route/?my_param=1%2C2");
});

test("getDataURLFromFile handles empty file", async () => {
    const emptyFile = new File([""], "empty.txt", { type: "text/plain" });
    const dataUrl = await getDataURLFromFile(emptyFile);
    expect(dataUrl).toBe("data:text/plain;base64,", {
        message: "dataURL for empty file is not proper",
    });
});

test("redirect", () => {
    function testRedirect(url) {
        browser.location = {
            protocol: "http:",
            host: "testhost",
            origin: "http://www.test.com",
            pathname: "/some/tests",
            href: "http://www.test.com",
            assign: (url) => {
                browser.location.href = url;
            },
        };
        redirect(url);
        return browser.location.href;
    }

    expect(testRedirect("abc")).toBe("http://www.test.com/some/abc");
    expect(testRedirect("./abc")).toBe("http://www.test.com/some/abc");
    expect(testRedirect("../abc/def")).toBe("http://www.test.com/abc/def");
    expect(testRedirect("/abc/def")).toBe("http://www.test.com/abc/def");
    expect(testRedirect("/abc/def?x=y")).toBe("http://www.test.com/abc/def?x=y");
    expect(testRedirect("/abc?x=y#a=1&b=2")).toBe(
        "http://www.test.com/abc?x=y#a=1&b=2",
    );

    expect(() => testRedirect("https://www.odoo.com")).toThrow(/Can't redirect/);
    expect(() => testRedirect("javascript:alert('boom');")).toThrow(/Can't redirect/);
});

describe("imageUrl", () => {
    test("builds a basic image route", () => {
        expect(imageUrl("res.partner", 1, "image_128")).toBe(
            "http://testhost/web/image/res.partner/1/image_128",
        );
    });

    test("passes a string unique through as a cache-busting token", () => {
        expect(imageUrl("res.partner", 1, "image", { unique: "abc" })).toBe(
            "http://testhost/web/image/res.partner/1/image?unique=abc",
        );
    });

    test("does not throw on a non-string unique", () => {
        // A truthy non-string non-DateTime unique (e.g. a numeric timestamp)
        // must not reach DateTime.fromSQL, which throws on non-strings.
        expect(() =>
            imageUrl("res.partner", 1, "image", { unique: 12345 }),
        ).not.toThrow();
        expect(imageUrl("res.partner", 1, "image", { unique: 12345 })).toBe(
            "http://testhost/web/image/res.partner/1/image?unique=12345",
        );
    });
});

describe("compareUrls", () => {
    test("identical URLs are equal", () => {
        expect(compareUrls("http://host/path?a=1", "http://host/path?a=1")).toBe(true);
    });

    test("query parameter order does not matter", () => {
        expect(
            compareUrls("http://host/path?a=1&b=2", "http://host/path?b=2&a=1"),
        ).toBe(true);
    });

    test("different origins are not equal", () => {
        expect(compareUrls("http://host1/path", "http://host2/path")).toBe(false);
    });

    test("different paths are not equal", () => {
        expect(compareUrls("http://host/a", "http://host/b")).toBe(false);
    });

    test("different query values are not equal", () => {
        expect(compareUrls("http://host/path?a=1", "http://host/path?a=2")).toBe(false);
    });

    test("extra query parameter makes URLs different", () => {
        expect(compareUrls("http://host/path?a=1", "http://host/path?a=1&b=2")).toBe(
            false,
        );
    });

    test("different hashes are not equal", () => {
        expect(compareUrls("http://host/path#a", "http://host/path#b")).toBe(false);
    });
});
