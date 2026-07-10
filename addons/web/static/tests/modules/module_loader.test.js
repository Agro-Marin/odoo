// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";

/**
 * ``module_loader.js`` has been in continuous simplification since the
 * fork-wide ESM migration completed.  The pre-2026 AMD behaviors
 * (``define()``, dependency-graph resolution, cycle detection, lazy
 * jobs, error reporter) were removed in the "shrink module_loader to
 * ESM-native surface" refactor because the esbuild-generated entry
 * exercises exactly one method — ``registerNativeModules`` — and no
 * other caller exists across the whole fork (verified: zero
 * ``odoo.define()`` calls in core, enterprise, design-themes,
 * agromarin).
 *
 * These tests cover the remaining surface:
 *   • ``modules`` Map lifecycle
 *   • ``registerNativeModules`` population + overwrite semantics
 *   • ``bus`` rebind events (different-namespace re-registration)
 *   • Idempotent install (``globalThis.odoo.loader`` not recreated by
 *     a sibling shim)
 *
 * ``module_loader.js`` is an inline pre-ESM shim, so it can't ``export``
 * its class — tests recover it from the live ambient instance via
 * ``odoo.loader.constructor``.  That handle is correct whether the page
 * installed the production ``new OdooModuleLoader()`` directly or (should
 * Hoot ever wrap it for isolated test-module graphs) a subclass: a
 * subclass inherits the full public surface these tests drive.  Using
 * ``Object.getPrototypeOf`` of the constructor would instead yield
 * ``Function.prototype`` for the shipped direct-instance shape and throw
 * "is not a constructor" — so we deliberately don't.
 */

/** @type {typeof OdooModuleLoader} */
const ModuleLoader = odoo.loader.constructor;

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
    const seen = [];
    loader.bus.addEventListener("rebind", (ev) => seen.push(ev.detail.specifiers));

    loader.registerNativeModules({ "@web/x": { v: "first" } });
    loader.registerNativeModules({ "@web/x": { v: "second" } });

    // Exactly one rebind, naming only the colliding specifier; the
    // Map still reflects last-write-wins.
    expect(seen).toEqual([["@web/x"]]);
    expect(loader.modules.get("@web/x")).toEqual({ v: "second" });
});

test("rebind: re-registering the SAME namespace object is silent", () => {
    const loader = new ModuleLoader();
    const ns = { v: "stable" };
    let fired = 0;
    loader.bus.addEventListener("rebind", () => fired++);

    // Repeat dynamic import / cross-doc bridge returns the cached
    // namespace — identity-equal, so no rebind.
    loader.registerNativeModules({ "@web/x": ns });
    loader.registerNativeModules({ "@web/x": ns });

    expect(fired).toBe(0);
    expect(loader.modules.size).toBe(1);
});

test("rebind: a mixed batch reports only the specifiers that changed", () => {
    const loader = new ModuleLoader();
    const stable = { a: 1 };
    const detered = [];
    loader.bus.addEventListener("rebind", (ev) =>
        detered.push(...ev.detail.specifiers),
    );

    loader.registerNativeModules({ "@web/a": stable, "@web/b": { b: 1 } });
    // @web/a unchanged (same object), @web/b rebound, @web/c is new.
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
    // Guard the idempotent-install contract in module_loader.js —
    // parallel bundle inlining on the same page must NOT replace the
    // loader with something that doesn't expose its surface.  Asserting
    // the structural contract (rather than ``instanceof ModuleLoader``,
    // which is tautological once ModuleLoader === odoo.loader.constructor)
    // also covers the hypothetical subclass shape.
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
        // Second failure inside the guard window: no second reload.
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
