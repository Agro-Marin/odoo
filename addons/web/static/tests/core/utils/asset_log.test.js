// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    actionLog,
    assetLog,
    componentLog,
    fieldLog,
    makeActionLog,
    makeAssetLog,
    makeComponentLog,
    makeModelLog,
    makeRpcLog,
    makeServiceLog,
    modelLog,
    rpcLog,
    serviceLog,
    viewLog,
} from "@web/core/utils/asset_log";

describe.current.tags("headless");

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

/**
 * Runs `body` with the structured sink armed and empty, then restores whatever
 * the surrounding page had. The sink lives on globalThis, so leaking it would
 * make one test's counts visible to the next.
 */
function withTraceSink(body) {
    const globals = globalThis;
    const priorFlag = globals.__odooTrace;
    const priorCounts = globals.__odooTraceCounts_;
    globals.__odooTrace = true;
    globals.__odooTraceReset();
    try {
        return body();
    } finally {
        globals.__odooTrace = priorFlag;
        globals.__odooTraceCounts_ = priorCounts;
    }
}

describe("namespaces added for the JS-improvement campaign", () => {
    test("component, service, view and field each expose enabled()", () => {
        expect(typeof componentLog.enabled).toBe("function");
        expect(typeof serviceLog.enabled).toBe("function");
        expect(typeof viewLog.enabled).toBe("function");
        expect(typeof fieldLog.enabled).toBe("function");
    });

    test("each is gated by its own localStorage flag and no other", () => {
        withLocalStorage("debug.service", "1", () => {
            expect(serviceLog.enabled()).toBe(true);
            expect(componentLog.enabled()).toBe(false);
            expect(viewLog.enabled()).toBe(false);
            expect(fieldLog.enabled()).toBe(false);
        });
    });

    test("emit under their own prefix", () => {
        const calls = captureConsoleDebug(() => {
            withLocalStorage("debug.view", "1", () => viewLog("load", "list"));
            withLocalStorage("debug.field", "1", () => fieldLog("resolve", "char"));
            withLocalStorage("debug.component", "1", () =>
                makeComponentLog("mount")("WebClient"),
            );
            withLocalStorage("debug.service", "1", () =>
                makeServiceLog("start")("orm"),
            );
        });
        expect(calls.map((c) => c[0])).toEqual([
            "[view.load]",
            "[field.resolve]",
            "[component.mount]",
            "[service.start]",
        ]);
    });
});

describe("structured sink (__odooTrace)", () => {
    test("off by default, so a normal page records nothing", () => {
        const globals = globalThis;
        const priorCounts = globals.__odooTraceCounts_;
        globals.__odooTraceReset();
        try {
            rpcLog("request", "/x");
            expect(globals.__odooTraceStats()).toEqual({});
        } finally {
            globals.__odooTraceCounts_ = priorCounts;
        }
    });

    test("counts by <namespace>.<category> when armed", () => {
        const stats = withTraceSink(() => {
            rpcLog("request", "/a");
            rpcLog("request", "/b");
            rpcLog("ok", "/a");
            viewLog("load", "form");
            return globalThis.__odooTraceStats();
        });
        expect(stats).toEqual({
            "rpc.request": 2,
            "rpc.ok": 1,
            "view.load": 1,
        });
    });

    test("records independently of the console gate", () => {
        const calls = captureConsoleDebug(() => {
            const stats = withTraceSink(() => {
                withLocalStorage("debug.model", "", () =>
                    modelLog("load", "res.partner"),
                );
                return globalThis.__odooTraceStats();
            });
            expect(stats).toEqual({ "model.load": 1 });
        });
        expect(calls.length).toBe(0);
    });

    test("__odooTraceStats returns a copy, not the live sink", () => {
        withTraceSink(() => {
            rpcLog("request", "/a");
            const first = globalThis.__odooTraceStats();
            rpcLog("request", "/b");
            expect(first["rpc.request"]).toBe(1);
            expect(globalThis.__odooTraceStats()["rpc.request"]).toBe(2);
        });
    });

    test("__odooTraceReset empties the sink", () => {
        withTraceSink(() => {
            rpcLog("request", "/a");
            globalThis.__odooTraceReset();
            expect(globalThis.__odooTraceStats()).toEqual({});
        });
    });

    test("the make* factories record under the category they bind", () => {
        const stats = withTraceSink(() => {
            makeServiceLog("start")("orm");
            makeComponentLog("mount")("WebClient");
            return globalThis.__odooTraceStats();
        });
        expect(stats).toEqual({ "service.start": 1, "component.mount": 1 });
    });
});

describe("active() — the guard a call site must use", () => {
    test("false when nothing listens", () => {
        withLocalStorage("debug.rpc", "", () => {
            const globals = globalThis;
            const prior = globals.__odooTrace;
            globals.__odooTrace = false;
            try {
                expect(rpcLog.active()).toBe(false);
            } finally {
                globals.__odooTrace = prior;
            }
        });
    });

    test("true when only the console gate is on", () => {
        const globals = globalThis;
        const prior = globals.__odooTrace;
        globals.__odooTrace = false;
        try {
            withLocalStorage("debug.rpc", "1", () => {
                expect(rpcLog.active()).toBe(true);
            });
        } finally {
            globals.__odooTrace = prior;
        }
    });

    test("true when only the structured sink is armed", () => {
        // The case enabled() cannot answer, and the reason active() exists: both
        // rpc.js listeners guarded on enabled(), so rpc.* recorded nothing on a
        // fully armed page boot until they moved to this predicate.
        withLocalStorage("debug.rpc", "", () => {
            const globals = globalThis;
            const prior = globals.__odooTrace;
            globals.__odooTrace = true;
            try {
                expect(rpcLog.enabled()).toBe(false);
                expect(rpcLog.active()).toBe(true);
            } finally {
                globals.__odooTrace = prior;
            }
        });
    });

    test("every namespace exposes it", () => {
        for (const log of [
            assetLog,
            rpcLog,
            actionLog,
            modelLog,
            componentLog,
            serviceLog,
            viewLog,
            fieldLog,
        ]) {
            expect(typeof log.active).toBe("function");
        }
    });
});
