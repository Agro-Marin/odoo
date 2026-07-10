// @ts-check

/** Pure unit tests for rpc_dedup.js: dedup of concurrent RPC calls, no OWL/DOM. */

import { describe, expect, test } from "@odoo/hoot";
import { buildKey } from "@web/core/network/rpc_dedup";

describe("buildKey", () => {
    test("produces identical keys for identical inputs", () => {
        const k1 = buildKey("/web/dataset/call_kw", { model: "res.partner" });
        const k2 = buildKey("/web/dataset/call_kw", { model: "res.partner" });
        expect(k1).toBe(k2);
    });

    test("produces different keys for different URLs", () => {
        const k1 = buildKey("/web/dataset/call_kw", { model: "res.partner" });
        const k2 = buildKey("/web/dataset/search_read", { model: "res.partner" });
        expect(k1).not.toBe(k2);
    });

    test("produces different keys for different params", () => {
        const k1 = buildKey("/rpc", { ids: [1] });
        const k2 = buildKey("/rpc", { ids: [2] });
        expect(k1).not.toBe(k2);
    });

    test("handles null params", () => {
        const k1 = buildKey("/rpc", null);
        const k2 = buildKey("/rpc", null);
        expect(k1).toBe(k2);
    });

    test("is insensitive to object key insertion order at every depth", () => {
        const k1 = buildKey("/rpc", {
            model: "res.partner",
            kwargs: { context: { lang: "en", tz: "utc", uid: 7 } },
        });
        const k2 = buildKey("/rpc", {
            kwargs: { context: { uid: 7, tz: "utc", lang: "en" } },
            model: "res.partner",
        });
        expect(k1).toBe(k2);
    });

    test("mirrors JSON.stringify semantics for the payload domain", () => {
        // undefined object entries are omitted; undefined array slots → null
        expect(buildKey("/rpc", { a: undefined, b: 1 })).toBe(
            buildKey("/rpc", { b: 1 }),
        );
        const withHole = buildKey("/rpc", { ids: [1, undefined, 3] });
        expect(withHole).toInclude("[1,null,3]");
        // toJSON is honored, as JSON.stringify would
        const k = buildKey("/rpc", { when: { toJSON: () => "2026-06-09" } });
        expect(k).toInclude('"when":"2026-06-09"');
        // arrays keep their order (only object KEYS are sorted)
        expect(buildKey("/rpc", { ids: [2, 1] })).not.toBe(
            buildKey("/rpc", { ids: [1, 2] }),
        );
        // the serialized form stays valid JSON (the cache's invalidateByModel
        // JSON.parses request keys)
        const parsed = JSON.parse(buildKey("/web/x", { model: "res.users" }));
        expect(parsed.params.model).toBe("res.users");
        expect(parsed.url).toBe("/web/x");
    });
});
