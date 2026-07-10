// @ts-check

/**
 * Pure unit tests for asset_log.js.
 *
 * Covers all four namespaced loggers (asset / rpc / action / model):
 *   - activation via localStorage["debug.<flag>"]
 *   - activation via odoo.debug substring
 *   - back-compat globalThis["__ODOO_ASSET_TRACE__"] for the asset namespace only
 *   - factory partial-application (makeXxxLog returns a function bound to a category)
 *   - log() short-circuits cleanly when disabled (no console call)
 *   - log() emits a `[<prefix>.<category>]`-prefixed console.debug when enabled
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    actionLog,
    assetLog,
    makeActionLog,
    makeAssetLog,
    makeModelLog,
    makeRpcLog,
    modelLog,
    rpcLog,
} from "@web/core/utils/asset_log";

describe.current.tags("headless");

/**
 * Save+set localStorage key, run the body, then restore — so tests don't
 * leak state into each other or into later test files in the same suite run.
 */
function withLocalStorage(key, value, body) {
    const prior = globalThis.localStorage.getItem(key);
    globalThis.localStorage.setItem(key, value);
    try {
        body();
    } finally {
        if (prior === null) {
            globalThis.localStorage.removeItem(key);
        } else {
            globalThis.localStorage.setItem(key, prior);
        }
    }
}

/**
 * Capture console.debug calls during body. Restores the original at the end.
 * Returns the list of capture entries (each entry is the args array).
 */
function captureConsoleDebug(body) {
    const captured = [];
    const original = console.debug;
    console.debug = (...args) => captured.push(args);
    try {
        body();
    } finally {
        console.debug = original;
    }
    return captured;
}

describe("enabled()", () => {
    test("all four loggers expose an .enabled() function", () => {
        expect(typeof assetLog.enabled).toBe("function");
        expect(typeof rpcLog.enabled).toBe("function");
        expect(typeof actionLog.enabled).toBe("function");
        expect(typeof modelLog.enabled).toBe("function");
    });

    test("disabled by default (no localStorage flag, no debug substring)", () => {
        // odoo.debug can't be reliably scrubbed here, so only assert on namespaces
        // whose substrings are unlikely to appear in it (rpc, action, model); asset
        // may already be enabled if the test runner ran with ?debug=assets.
        if (!globalThis.localStorage.getItem("debug.rpc")) {
            expect(rpcLog.enabled()).toBe(false);
        }
        if (!globalThis.localStorage.getItem("debug.action")) {
            expect(actionLog.enabled()).toBe(false);
        }
        if (!globalThis.localStorage.getItem("debug.model")) {
            expect(modelLog.enabled()).toBe(false);
        }
    });

    test("localStorage flag activates the matching namespace", () => {
        withLocalStorage("debug.rpc", "1", () => {
            expect(rpcLog.enabled()).toBe(true);
        });
        withLocalStorage("debug.action", "1", () => {
            expect(actionLog.enabled()).toBe(true);
        });
        withLocalStorage("debug.model", "1", () => {
            expect(modelLog.enabled()).toBe(true);
        });
    });

    test("localStorage flag for one namespace does NOT activate another", () => {
        withLocalStorage("debug.rpc", "1", () => {
            expect(actionLog.enabled()).toBe(false);
            expect(modelLog.enabled()).toBe(false);
        });
    });

    test("back-compat: __ODOO_ASSET_TRACE__ activates the asset namespace only", () => {
        const had = "__ODOO_ASSET_TRACE__" in /** @type {any} */ (globalThis);
        const prior = /** @type {any} */ (globalThis).__ODOO_ASSET_TRACE__;
        /** @type {any} */ (globalThis).__ODOO_ASSET_TRACE__ = true;
        try {
            expect(assetLog.enabled()).toBe(true);
            // Other namespaces don't carry the legacy global flag —
            // they require their own localStorage key / debug substring.
            withLocalStorage("debug.rpc", "", () => {
                expect(rpcLog.enabled()).toBe(false);
            });
        } finally {
            if (had) {
                /** @type {any} */ (globalThis).__ODOO_ASSET_TRACE__ = prior;
            } else {
                delete (/** @type {any} */ (globalThis).__ODOO_ASSET_TRACE__);
            }
        }
    });
});

describe("log emission", () => {
    test("short-circuits to no-op when disabled", () => {
        const calls = captureConsoleDebug(() => {
            // Ensure all four namespaces are quiet; scope each call to clear only
            // its own key in case the caller's localStorage set others.
            withLocalStorage("debug.rpc", "", () => rpcLog("test", "x"));
            withLocalStorage("debug.action", "", () => actionLog("test", "x"));
            withLocalStorage("debug.model", "", () => modelLog("test", "x"));
        });
        expect(calls.length).toBe(0);
    });

    test("emits [<prefix>.<category>] when enabled", () => {
        const calls = captureConsoleDebug(() => {
            withLocalStorage("debug.rpc", "1", () => {
                rpcLog("request", "/web/dataset/call_kw/res.partner/read");
            });
        });
        expect(calls.length).toBe(1);
        expect(calls[0][0]).toBe("[rpc.request]");
        expect(calls[0][1]).toBe("/web/dataset/call_kw/res.partner/read");
    });

    test("passes through extra parts unchanged (multi-arg)", () => {
        const calls = captureConsoleDebug(() => {
            withLocalStorage("debug.model", "1", () => {
                modelLog("load", "res.partner", { resId: 42, limit: 80 });
            });
        });
        expect(calls.length).toBe(1);
        expect(calls[0][0]).toBe("[model.load]");
        expect(calls[0][1]).toBe("res.partner");
        expect(calls[0][2]).toEqual({ resId: 42, limit: 80 });
    });
});

describe("makeXxxLog factory", () => {
    test("returns a function bound to the given category", () => {
        const log = makeRpcLog("custom");
        expect(typeof log).toBe("function");
        const calls = captureConsoleDebug(() => {
            withLocalStorage("debug.rpc", "1", () => log("hello"));
        });
        expect(calls.length).toBe(1);
        expect(calls[0][0]).toBe("[rpc.custom]");
        expect(calls[0][1]).toBe("hello");
    });

    test("all four make* factories produce category-bound loggers", () => {
        // Sanity check that no factory is broken (e.g. typo in prefix).
        const calls = captureConsoleDebug(() => {
            withLocalStorage("debug.assets", "1", () => makeAssetLog("a")("payload"));
            withLocalStorage("debug.rpc", "1", () => makeRpcLog("b")("payload"));
            withLocalStorage("debug.action", "1", () => makeActionLog("c")("payload"));
            withLocalStorage("debug.model", "1", () => makeModelLog("d")("payload"));
        });
        expect(calls.length).toBe(4);
        expect(calls[0][0]).toBe("[asset.a]");
        expect(calls[1][0]).toBe("[rpc.b]");
        expect(calls[2][0]).toBe("[action.c]");
        expect(calls[3][0]).toBe("[model.d]");
    });
});
