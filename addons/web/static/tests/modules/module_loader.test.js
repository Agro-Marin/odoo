// @ts-check

import { describe, expect, test } from "@odoo/hoot";

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
 *   • Idempotent install (``globalThis.odoo.loader`` not recreated by
 *     a sibling shim)
 *
 * The prototype chain (``Object.getPrototypeOf(odoo.loader.constructor)``)
 * is used by Hoot's test runner to subclass the loader for isolated
 * test-module graphs; preserving the class shell keeps that pattern
 * working.
 */

/** @type {typeof OdooModuleLoader} */
const ModuleLoader = Object.getPrototypeOf(odoo.loader.constructor);

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

test("registerNativeModules: subsequent calls accumulate entries", () => {
    const loader = new ModuleLoader();

    loader.registerNativeModules({ "@web/a": { a: 1 } });
    loader.registerNativeModules({ "@web/b": { b: 2 } });
    loader.registerNativeModules({ "@web/c": { c: 3 } });

    expect(loader.modules.size).toBe(3);
    expect([...loader.modules.keys()].sort()).toEqual([
        "@web/a", "@web/b", "@web/c",
    ]);
});

test("ambient odoo.loader is a singleton instance of OdooModuleLoader", () => {
    // Guard against accidental breakage of the idempotent-install
    // contract in module_loader.js — parallel bundle inlining on the
    // same page must NOT replace the loader.
    expect(odoo.loader).toBeInstanceOf(ModuleLoader);
    expect(odoo.loader.modules).toBeInstanceOf(Map);
});
