// @ts-check

import { after, describe, expect, mockSendBeacon, test } from "@odoo/hoot";

/**
 * ``module_loader.js``'s pre-2026 AMD behaviors (``define()``, dependency-graph
 * resolution, cycle detection, lazy jobs, error reporter) were removed once the
 * fork-wide ESM migration completed: the esbuild entry exercises only
 * ``registerNativeModules``, and no ``odoo.define()`` calls remain anywhere in
 * the fork.
 *
 * ``module_loader.js`` is an inline pre-ESM shim that can't ``export`` its
 * class, so tests recover it via ``odoo.loader.constructor``. Using
 * ``Object.getPrototypeOf`` of the constructor would instead yield
 * ``Function.prototype`` for the shipped direct-instance shape and throw
 * "is not a constructor".
 */

const ModuleLoader = /** @type {typeof OdooModuleLoader} */ (odoo.loader.constructor);

describe.current.tags("headless");

test("fresh loader: modules Map is empty", () => {
    const loader = new ModuleLoader();
    expect(loader.modules).toBeEmpty();
});

test("registerNativeModules: populates modules for every entry", () => {
    const loader = new ModuleLoader();
    const nsA = { foo: 1 };
    const nsB = { bar: 2 };

    loader.registerNativeModules({ "@web/a": nsA, "@web/b": nsB });

    expect(loader.modules.size).toBe(2);
    expect(loader.modules.get("@web/a")).toBe(nsA);
    expect(loader.modules.get("@web/b")).toBe(nsB);
});

test("registerNativeModules: accepts an empty map without error", () => {
    const loader = new ModuleLoader();
    loader.registerNativeModules({});
    expect(loader.modules).toBeEmpty();
});

test("registerNativeModules: last-write-wins on same specifier", () => {
    const loader = new ModuleLoader();
    const first = { v: "first" };
    const second = { v: "second" };

    loader.registerNativeModules({ "@web/x": first });
    loader.registerNativeModules({ "@web/x": second });

    expect(loader.modules.get("@web/x")).toBe(second);
    expect(loader.modules.size).toBe(1);
});

test("bus: fresh loader exposes an EventTarget", () => {
    const loader = new ModuleLoader();
    expect(loader.bus).toBeInstanceOf(EventTarget);
});

test("rebind: re-binding a specifier to a DIFFERENT namespace fires the event", () => {
    const loader = new ModuleLoader();
    /** @type {any[]} */
    const seen = [];
    loader.bus.addEventListener("rebind", (/** @type {any} */ ev) =>
        seen.push(ev.detail.specifiers),
    );

    loader.registerNativeModules({ "@web/x": { v: "first" } });
    loader.registerNativeModules({ "@web/x": { v: "second" } });

    expect(seen).toEqual([["@web/x"]]);
    expect(loader.modules.get("@web/x")).toEqual({ v: "second" });
});

test("rebind: re-registering the SAME namespace object is silent", () => {
    const loader = new ModuleLoader();
    const ns = { v: "stable" };
    let fired = 0;
    loader.bus.addEventListener("rebind", () => fired++);

    loader.registerNativeModules({ "@web/x": ns });
    loader.registerNativeModules({ "@web/x": ns });

    expect(fired).toBe(0);
    expect(loader.modules.size).toBe(1);
});

test("rebind: a mixed batch reports only the specifiers that changed", () => {
    const loader = new ModuleLoader();
    const stable = { a: 1 };
    /** @type {any[]} */
    const detered = [];
    loader.bus.addEventListener("rebind", (/** @type {any} */ ev) =>
        detered.push(...ev.detail.specifiers),
    );

    loader.registerNativeModules({ "@web/a": stable, "@web/b": { b: 1 } });
    loader.registerNativeModules({
        "@web/a": stable,
        "@web/b": { b: 2 },
        "@web/c": { c: 1 },
    });

    expect(detered).toEqual(["@web/b"]);
    expect(loader.modules.size).toBe(3);
});

test("registerNativeModules: subsequent calls accumulate entries", () => {
    const loader = new ModuleLoader();

    loader.registerNativeModules({ "@web/a": { a: 1 } });
    loader.registerNativeModules({ "@web/b": { b: 2 } });
    loader.registerNativeModules({ "@web/c": { c: 3 } });

    expect(loader.modules.size).toBe(3);
    expect([...loader.modules.keys()].sort()).toEqual(["@web/a", "@web/b", "@web/c"]);
});

test("ambient odoo.loader exposes the full loader contract", () => {
    expect(odoo.loader.modules).toBeInstanceOf(Map);
    expect(odoo.loader.bus).toBeInstanceOf(EventTarget);
    expect(typeof odoo.loader.registerNativeModules).toBe("function");
});

describe("asset load self-heal", () => {
    const GUARD_KEY = "odoo-asset-reload-ts";

    /** @param {string | null} value */
    function withGuard(value) {
        const previous = sessionStorage.getItem(GUARD_KEY);
        if (value === null) {
            sessionStorage.removeItem(GUARD_KEY);
        } else {
            sessionStorage.setItem(GUARD_KEY, value);
        }
        after(() => {
            if (previous === null) {
                sessionStorage.removeItem(GUARD_KEY);
            } else {
                sessionStorage.setItem(GUARD_KEY, previous);
            }
        });
    }

    /** @param {Record<string, string>} [attrs] */
    function makeScript(attrs = {}) {
        const script = document.createElement("script");
        for (const [name, value] of Object.entries(attrs)) {
            script.setAttribute(name, value);
        }
        return script;
    }

    test("failing bundle script triggers one reload", () => {
        withGuard(null);
        const loader = new ModuleLoader();
        const reloads = [];
        loader._reloadPage = () => reloads.push(1);

        const script = makeScript({
            src: "/web/assets/esm/abc123/web.assets_web.esm.js",
        });
        expect(loader.handleAssetLoadError(script)).toBe(true);
        expect(reloads).toHaveLength(1);
        expect(loader.handleAssetLoadError(script)).toBe(false);
        expect(reloads).toHaveLength(1);
    });

    test("expired guard window allows a fresh reload", () => {
        withGuard(String(Date.now() - 120_000));
        const loader = new ModuleLoader();
        const reloads = [];
        loader._reloadPage = () => reloads.push(1);

        const script = makeScript({ src: "/web/assets/1/web.assets_web.js" });
        expect(loader.handleAssetLoadError(script)).toBe(true);
        expect(reloads).toHaveLength(1);
    });

    test("non-bundle script failures are ignored", () => {
        withGuard(null);
        const loader = new ModuleLoader();
        loader._reloadPage = () => expect.step("reload");

        expect(
            loader.handleAssetLoadError(makeScript({ src: "/some/other/app.js" })),
        ).toBe(false);
        expect(loader.handleAssetLoadError(makeScript())).toBe(false);
        expect(loader.handleAssetLoadError(document.createElement("link"))).toBe(false);
        expect(loader.handleAssetLoadError(null)).toBe(false);
        expect.verifySteps([]);
    });

    test("failing bundle stylesheet (LINK) triggers one reload", () => {
        withGuard(null);
        const loader = new ModuleLoader();
        const reloads = [];
        loader._reloadPage = () => reloads.push(1);

        const link = document.createElement("link");
        link.setAttribute("rel", "stylesheet");
        link.setAttribute("href", "/web/assets/1/web.assets_web.min.css");
        expect(loader.handleAssetLoadError(link)).toBe(true);
        expect(reloads).toHaveLength(1);

        const otherLink = document.createElement("link");
        otherLink.setAttribute("href", "/some/other/style.css");
        expect(loader.handleAssetLoadError(otherLink)).toBe(false);
        expect(reloads).toHaveLength(1);
    });

    test("lazy-load scripts (data-src) are covered", () => {
        withGuard(null);
        const loader = new ModuleLoader();
        const reloads = [];
        loader._reloadPage = () => reloads.push(1);

        const script = makeScript({
            "data-src": "/web/assets/1/web.assets_web_print.js",
        });
        expect(loader.handleAssetLoadError(script)).toBe(true);
        expect(reloads).toHaveLength(1);
    });
});

/**
 * The beacon logic below is a byte-identical copy of
 * ``@web/core/errors/error_beacon`` — the shim is pre-ESM and cannot import it.
 * These tests reach it through ``odoo.loader._beacon``, the seam the shim
 * exposes for exactly this reason (same rationale as ``_reloadPage``).
 *
 * ``seenErrors`` is module-level and lives for the whole page, so every dedup
 * test clears it first; otherwise an earlier test's key silently suppresses a
 * later one's beacon and the failure looks like a logic bug.
 */
describe("beacon (inlined copy)", () => {
    test("hashCode: stable per input, and distinct across inputs", () => {
        const { hashCode } = odoo.loader._beacon;
        expect(hashCode("at foo (foo.js:1:1)")).toBe(hashCode("at foo (foo.js:1:1)"));
        expect(hashCode("at foo (foo.js:1:1)")).not.toBe(
            hashCode("at bar (bar.js:2:2)"),
        );
        expect(hashCode("")).toHaveLength(8);
    });

    test("serializeCause: an Error chain is flattened in order", () => {
        const { serializeCause } = odoo.loader._beacon;
        const root = new RangeError("root");
        const mid = new Error("mid", { cause: root });
        expect(serializeCause(mid)).toBe(
            "Caused by: Error: mid\nCaused by: RangeError: root",
        );
    });

    test("serializeCause: a cycle terminates instead of spinning", () => {
        const { serializeCause } = odoo.loader._beacon;
        const a = new Error("a");
        const b = new Error("b", { cause: a });
        /** @type {any} */ (a).cause = b;
        expect(serializeCause(b)).toInclude("[circular]");
    });

    test("serializeCause: depth is capped at 8 levels", () => {
        const { serializeCause } = odoo.loader._beacon;
        let deepest = new Error("level-0");
        for (let i = 1; i < 20; i++) {
            deepest = new Error(`level-${i}`, { cause: deepest });
        }
        expect(serializeCause(deepest).split("\n")).toHaveLength(8);
    });

    test("serializeCause: non-Error and absent causes degrade cleanly", () => {
        const { serializeCause } = odoo.loader._beacon;
        expect(serializeCause("plain")).toBe("Caused by: plain");
        expect(serializeCause({ code: 500 })).toBe('Caused by: {"code":500}');
        expect(serializeCause({ n: 1n })).toBe("Caused by: [unserializable]");
        expect(serializeCause(undefined)).toBe("");
        expect(serializeCause(null)).toBe("");
    });

    test("reportError: a different stack is a distinct beacon", async () => {
        const { reportError, seenErrors } = odoo.loader._beacon;
        seenErrors.clear();
        const calls = [];
        mockSendBeacon((url, blob) => {
            calls.push(blob);
            return true;
        });
        // The regression: OWL reports every lifecycle failure with one generic
        // message at 0:0, so these two used to collapse into a single beacon.
        const base = { message: "owl lifecycle", line: 0, col: 0 };
        reportError({ ...base, stack: "at A (a.js:1:1)" });
        reportError({ ...base, stack: "at B (b.js:2:2)" });
        expect(calls).toHaveLength(2);
    });

    test("reportError: an exact repeat is still throttled", () => {
        const { reportError, seenErrors } = odoo.loader._beacon;
        seenErrors.clear();
        const calls = [];
        mockSendBeacon((url, blob) => {
            calls.push(blob);
            return true;
        });
        const info = { message: "same", line: 1, col: 1, stack: "at same (s.js:1:1)" };
        reportError({ ...info });
        reportError({ ...info });
        expect(calls).toHaveLength(1);
    });
});
