// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getKey } from "@web/core/network/rpc_dedup";

describe.current.tags("headless");

describe("getKey", () => {
    test("produces identical keys for identical inputs", () => {
        const k1 = getKey("/web/dataset/call_kw", { model: "res.partner" });
        const k2 = getKey("/web/dataset/call_kw", { model: "res.partner" });
        expect(k1).toBe(k2);
    });

    test("produces different keys for different URLs", () => {
        const k1 = getKey("/web/dataset/call_kw", { model: "res.partner" });
        const k2 = getKey("/web/dataset/search_read", { model: "res.partner" });
        expect(k1).not.toBe(k2);
    });

    test("produces different keys for different params", () => {
        const k1 = getKey("/rpc", { ids: [1] });
        const k2 = getKey("/rpc", { ids: [2] });
        expect(k1).not.toBe(k2);
    });

    test("handles null params", () => {
        const k1 = getKey("/rpc", null);
        const k2 = getKey("/rpc", null);
        expect(k1).toBe(k2);
    });

    test("is insensitive to object key insertion order at every depth", () => {
        const k1 = getKey("/rpc", {
            model: "res.partner",
            kwargs: { context: { lang: "en", tz: "utc", uid: 7 } },
        });
        const k2 = getKey("/rpc", {
            kwargs: { context: { uid: 7, tz: "utc", lang: "en" } },
            model: "res.partner",
        });
        expect(k1).toBe(k2);
    });

    test("mirrors JSON.stringify semantics for the payload domain", () => {
        expect(getKey("/rpc", { a: undefined, b: 1 })).toBe(getKey("/rpc", { b: 1 }));
        const withHole = getKey("/rpc", { ids: [1, undefined, 3] });
        expect(withHole).toInclude("[1,null,3]");
        const k = getKey("/rpc", { when: { toJSON: () => "2026-06-09" } });
        expect(k).toInclude('"when":"2026-06-09"');
        expect(getKey("/rpc", { ids: [2, 1] })).not.toBe(
            getKey("/rpc", { ids: [1, 2] }),
        );
        const parsed = JSON.parse(getKey("/web/x", { model: "res.users" }));
        expect(parsed.params.model).toBe("res.users");
        expect(parsed.url).toBe("/web/x");
    });
});
