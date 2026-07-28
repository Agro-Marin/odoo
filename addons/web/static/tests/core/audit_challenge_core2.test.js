// @ts-check

/**
 * AUDIT CHALLENGE (round 2) — executable proofs for core-layer findings.
 *
 * Each test asserts the CORRECT behaviour, so it fails against the current
 * implementation and passes once the finding is fixed.
 */

import { Deferred, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { mockIndexedDBForTests } from "@web/../tests/_framework/mock_indexed_db.hoot";
import { assetCacheByDocument, assets } from "@web/core/assets";
import { Domain, InvalidDomainError } from "@web/core/domain";
import { RPCCache } from "@web/core/network/rpc_cache";
import { buildKey } from "@web/core/network/rpc_dedup";
import { toPyValue } from "@web/core/py_js/py_utils";
import { Cache } from "@web/core/utils/collections/cache";
import { createWaveResolver } from "@web/core/utils/dependency_graph";
import { orderByToString, stringToOrderBy } from "@web/core/utils/order_by";
import { patch, patchDeclaredKeys } from "@web/core/utils/patch";
import { fuzzyLookup, fuzzyTest } from "@web/core/utils/search";

mockIndexedDBForTests();

describe.current.tags("headless");

const SECRET = "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b";

describe("RPCCache.invalidateByModel", () => {
    test("drops an in-flight request whose table name contains a slash", async () => {
        const cache = new RPCCache("audit", 1, SECRET);
        const table = "/web/dataset/call_kw";
        const key = JSON.stringify({
            params: { model: "res.partner", method: "web_search_read" },
            url: table,
        });
        const def = new Deferred();
        cache.read(table, key, () => def, { model: "res.partner" });
        expect(Object.keys(cache.pendingRequests)).toHaveLength(1);

        cache.invalidateByModel([table], "res.partner");

        expect(Object.keys(cache.pendingRequests)).toEqual([]);
        def.resolve({ ok: true });
        await def;
    });

    test("keeps an in-flight request registered under a different model", async () => {
        const cache = new RPCCache("audit", 1, SECRET);
        const table = "/web/dataset/call_kw";
        const def = new Deferred();
        cache.read(table, "k", () => def, { model: "res.users" });

        cache.invalidateByModel([table], "res.partner");

        expect(Object.keys(cache.pendingRequests)).toHaveLength(1);
        def.resolve({ ok: true });
        await def;
    });

    // The only production trigger (result_set_cache_invalidator_service) passes
    // these slash-free tables, which the previous key-parsing handled correctly.
    // Pinned so the rewrite is proven equivalent on the live wiring.
    test("still invalidates on the production table set", async () => {
        const cache = new RPCCache("audit", 1, SECRET);
        const table = "web_search_read";
        const key = buildKey(`/web/dataset/call_kw/res.partner/${table}`, {
            model: "res.partner",
            method: table,
        });
        const def = new Deferred();
        cache.read(table, key, () => def, { model: "res.partner" });

        cache.invalidateByModel(
            ["web_read", "web_search_read", "web_read_group"],
            "res.partner",
        );

        expect(Object.keys(cache.pendingRequests)).toEqual([]);
        def.resolve({ ok: true });
        await def;
    });
});

describe("patch", () => {
    test("re-patching a released extension does not re-apply foreign keys", () => {
        const target = {
            a() {
                return "A";
            },
            b() {
                return "B";
            },
        };
        const extA = {
            a() {
                return "extA";
            },
        };
        const extB = {
            b() {
                return "extB";
            },
        };
        const unpatchA = patch(target, extA);
        patch(target, extB);

        // Releasing extA must leave extB's contribution in place.
        unpatchA();
        expect(target.a()).toBe("A");
        expect(target.b()).toBe("extB");

        // Re-applying extA must only touch the key extA declared ("a").
        // `patch()` copies the previous descriptor of every overridden key onto
        // the CURRENT skeleton — which is the previous extension object — so
        // extA silently acquired an own `b` holding the ORIGINAL `b`.
        patch(target, extA);
        expect(target.a()).toBe("extA");
        expect(target.b()).toBe("extB");
    });

    test("the super chain survives an unpatch/re-patch round trip", () => {
        const target = {
            a() {
                return "A";
            },
            b() {
                return "B";
            },
        };
        const extA = {
            a() {
                return `extA(${/** @type {any} */ (Object.getPrototypeOf(extA)).a.call(this)})`;
            },
        };
        const extB = {
            b() {
                return "extB";
            },
        };
        const unpatchA = patch(target, extA);
        patch(target, extB);
        expect(target.a()).toBe("extA(A)");

        unpatchA();
        patch(target, extA);
        expect(target.a()).toBe("extA(A)");
        expect(target.b()).toBe("extB");
    });

    test("declared keys stay honest once an extension has served as a skeleton", () => {
        const target = { a: () => "A", b: () => "B" };
        const extA = { a: () => "extA" };
        const extB = { b: () => "extB" };
        patch(target, extA);
        patch(target, extB);
        expect(Object.hasOwn(extA, "b")).toBe(true);
        expect(patchDeclaredKeys(extA)).toEqual(["a"]);
    });
});

describe("order_by", () => {
    test("round-trips a term that omits `asc`", () => {
        expect(stringToOrderBy(orderByToString([{ name: "foo" }]))).toEqual([
            { name: "foo", asc: true },
        ]);
    });
});

describe("assets cache eviction", () => {
    /**
     * Start a load, drop its cache entry, install a sentinel in its place, then
     * fail the ORIGINAL load. The sentinel must survive: the older load owns a
     * different promise and has no business evicting whatever replaced it.
     *
     * The url lives under ``/web/assets/`` so ``loadCSS`` treats the failure as
     * final instead of retrying, and the element is failed by dispatching
     * "error" on it directly — no global event, no real request outcome to wait
     * on, so the probe cannot disturb loads owned by other tests.
     *
     * @param {"loadJS" | "loadCSS"} fn
     * @param {string} selector
     */
    const survivesFailure = async (fn, selector) => {
        const cacheMap = /** @type {Map<string, any>} */ (
            assetCacheByDocument.get(document)
        );
        const url = `/web/assets/audit_${fn}_${Math.random()}`;
        assets[fn](url).catch(() => {});
        const el = document.head.querySelector(selector.replace("%s", url));
        cacheMap.delete(url);
        const sentinel = Promise.resolve();
        cacheMap.set(url, sentinel);

        el?.dispatchEvent(new Event("error"));
        el?.remove();
        await animationFrame();

        const survived = cacheMap.get(url) === sentinel;
        cacheMap.delete(url);
        return survived;
    };

    test("loadCSS does not evict an entry it does not own", async () => {
        expect(await survivesFailure("loadCSS", `link[href="%s"]`)).toBe(true);
    });

    test("loadJS does not evict an entry it does not own", async () => {
        expect(await survivesFailure("loadJS", `script[src="%s"]`)).toBe(true);
    });
});

describe("fuzzy search with an empty pattern", () => {
    test("fuzzyLookup('') returns the whole list, in order", () => {
        expect(fuzzyLookup("", ["alpha", "beta", "gamma"], (s) => s)).toEqual([
            "alpha",
            "beta",
            "gamma",
        ]);
    });

    test("fuzzyLookup('') returns a copy, not the caller's array", () => {
        const list = ["a"];
        expect(fuzzyLookup("", list, (s) => s)).not.toBe(list);
    });

    test("fuzzyTest('', str) is true", () => {
        expect(fuzzyTest("", "anything")).toBe(true);
    });

    test("a non-empty pattern still filters", () => {
        expect(fuzzyLookup("ga", ["alpha", "gamma"], (s) => s)).toEqual(["gamma"]);
        expect(fuzzyTest("zz", "anything")).toBe(false);
    });
});

describe("toPyValue", () => {
    test("emits own keys only", () => {
        const obj = Object.create({ inherited: 1 });
        obj.own = 2;
        expect(Object.keys(/** @type {any} */ (toPyValue(obj)).value)).toEqual(["own"]);
    });

    test("an inherited property never reaches the serialized domain", () => {
        const value = Object.create({ extra: "leaked" });
        value.real = "kept";
        const serialized = new Domain([["f", "=", value]]).toString();
        expect(serialized).toInclude("kept");
        expect(serialized).not.toInclude("leaked");
    });
});

describe("Domain leaf validation", () => {
    test("a non-string operator raises InvalidDomainError", () => {
        expect(() =>
            new Domain([["a", /** @type {any} */ (5), 1]]).contains({ a: 1 }),
        ).toThrow(InvalidDomainError);
    });
});

describe("Cache", () => {
    test("rejects an empty lookup path instead of keying on 'undefined'", () => {
        const c = new Cache(() => 1);
        expect(() => c.read()).toThrow(TypeError);
        expect(() => c.clear()).toThrow(TypeError);
        expect(() => c.set(1)).toThrow(TypeError);
    });

    test("an explicit getKey still allows a zero-segment path", () => {
        const c = new Cache(
            () => "v",
            () => "fixed",
        );
        expect(c.read()).toBe("v");
    });
});

describe("createWaveResolver", () => {
    test("untrack removes a ready entry from the queue", () => {
        const r = createWaveResolver({ isLoaded: () => true });
        r.track("a", []);
        r.track("b", []);
        r.untrack("a");
        expect(r.shift()).toBe("b");
        expect(r.shift()).toBe(undefined);
        expect(r.hasReady()).toBe(false);
    });
});
