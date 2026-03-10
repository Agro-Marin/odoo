// @ts-check

import { beforeEach, expect, getFixture, test } from "@odoo/hoot";
import { microTick, tick } from "@odoo/hoot-dom";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

beforeEach(() => {
    patchWithCleanup(document.head, {
        appendChild: (el) => expect.step(["APPENDCHILD", el.tagName, el.className]),
    });
    patchWithCleanup(console, {
        error: (...args) => expect.step(["ERROR", ...args]),
    });
});

/** @type {typeof OdooModuleLoader} */
const ModuleLoader = Object.getPrototypeOf(odoo.loader.constructor);

test.tags("headless");
test("define: simple case", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    const modA = {};
    const modC = {};

    expect(loader.factories).toBeEmpty();
    expect(loader.modules).toBeEmpty();
    expect(loader.checkErrorProm).toBe(null);

    loader.define("b", ["c"], (req) => req("c"));
    loader.define("c", [], () => modC);
    loader.define("a", ["b"], () => modA);

    expect(loader.factories).toHaveLength(3);
    expect(loader.modules).toHaveLength(3);
    expect(loader.failed).toBeEmpty();
    expect(loader.jobs).toBeEmpty();

    expect(loader.modules.get("a")).toBe(modA);
    expect(loader.modules.get("b")).toBe(modC);
    expect(loader.modules.get("c")).toBe(modC);

    Promise.resolve(loader.checkErrorProm).then(() => expect.step("check done"));

    expect.verifySteps([]);

    await tick();

    expect.verifySteps(["check done"]);
});

test.tags("headless");
test("define: invalid module error handling", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    expect(() => loader.define(null, null, null)).toThrow(
        /Module name should be a string/,
    );
    expect(() => loader.define("a", null, null)).toThrow(
        /Module dependencies should be a list of strings/,
    );
    expect(() => loader.define("a", [], null)).toThrow(
        /Module factory should be a function/,
    );

    expect(loader.checkErrorProm).toBe(null);
});

test.tags("headless");
test("define: duplicate name", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    loader.define("a", [], () => ":)");
    loader.define("a", [], () => {
        throw new Error("This factory should be ignored");
    });

    await microTick();

    expect(loader.modules.get("a")).toBe(":)");
});

test("define: missing module", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    loader.define("b", ["a"], () => {});
    loader.define("c", ["a"], () => {});

    await microTick();

    expect.verifySteps([
        [
            "ERROR",
            "The following modules are needed by other modules but have not been defined, they may not be present in the correct asset bundle:",
            ["a"],
        ],
        [
            "ERROR",
            "The following modules could not be loaded because they have unmet dependencies, this is a secondary error which is likely caused by one of the above problems:",
            ["b", "c"],
        ],
    ]);
});

test.tags("headless");
test("define: factory error does not block independent modules", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    const modC = { value: "ok" };

    // "a" has no deps and will throw when its factory runs
    loader.define("a", [], () => {
        throw new Error("boom");
    });
    // "b" depends on "a" — must NOT start (dependency failed, never in modules)
    loader.define("b", ["a"], () => ({ value: "should not load" }));
    // "c" is independent — must still start despite "a" failing
    loader.define("c", [], () => modC);

    expect(loader.failed).toEqual(new Set(["a"]));
    expect(loader.modules.has("a")).toBe(false);
    expect(loader.modules.has("b")).toBe(false);
    expect(loader.modules.get("c")).toBe(modC);

    await microTick();

    // The catch in startModules logs: error.message + error.cause
    // Then findErrors reports failed + unloaded via checkErrorProm
    expect.verifySteps([
        ["ERROR", 'Error while loading "a"', new Error("boom")],
        ["ERROR", "The following modules failed to load because of an error:", ["a"]],
        [
            "ERROR",
            "The following modules could not be loaded because they have unmet dependencies, this is a secondary error which is likely caused by one of the above problems:",
            ["b"],
        ],
    ]);
});

test.tags("headless");
test("define: multiple factory errors, survivors still load", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    const modD = { value: "survivor" };

    loader.define("x", [], () => {
        throw new Error("x broke");
    });
    loader.define("y", [], () => {
        throw new Error("y broke");
    });
    // "z" depends on "x" — blocked
    loader.define("z", ["x"], () => ({}));
    // "d" is independent — must survive
    loader.define("d", [], () => modD);

    expect(loader.failed).toEqual(new Set(["x", "y"]));
    expect(loader.modules.has("x")).toBe(false);
    expect(loader.modules.has("y")).toBe(false);
    expect(loader.modules.has("z")).toBe(false);
    expect(loader.modules.get("d")).toBe(modD);
});

test.tags("headless");
test("define: late module loads after earlier failure", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    loader.define("a", [], () => {
        throw new Error("a broke");
    });

    expect(loader.failed).toEqual(new Set(["a"]));

    // A module defined later with no relation to "a" must still start
    const modLate = { value: "late" };
    loader.define("late", [], () => modLate);

    expect(loader.modules.get("late")).toBe(modLate);
});

test("define: dependency cycle", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = true;

    loader.define("a", ["b"], () => {});
    loader.define("b", ["c"], () => {});
    loader.define("c", ["a"], () => {});

    await microTick();

    expect.verifySteps([
        [
            "ERROR",
            "The following modules could not be loaded because they form a dependency cycle:",
            `"a" => "b" => "c" => "a"`,
        ],
        [
            "ERROR",
            "The following modules could not be loaded because they have unmet dependencies, this is a secondary error which is likely caused by one of the above problems:",
            ["a", "b", "c"],
        ],
        ["APPENDCHILD", "STYLE", "o_module_error_banner"],
    ]);
});

// --- O(N+E) dependency resolution tests ---

test.tags("headless");
test("define: reverse definition order (deps after dependents)", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    // Define dependents before their dependencies (worst case for naive scan)
    const results = [];
    loader.define("d", ["c"], () => results.push("d"));
    loader.define("c", ["b"], () => results.push("c"));
    loader.define("b", ["a"], () => results.push("b"));
    loader.define("a", [], () => results.push("a"));

    // All should load: "a" triggers "b", which triggers "c", which triggers "d"
    expect(loader.modules).toHaveLength(4);
    expect(loader.jobs).toBeEmpty();
    expect(results).toEqual(["a", "b", "c", "d"]);
});

test.tags("headless");
test("define: diamond dependency", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    // Diamond: d depends on both b and c, which both depend on a
    //     a
    //    / \
    //   b   c
    //    \ /
    //     d
    const results = [];
    loader.define("d", ["b", "c"], () => results.push("d"));
    loader.define("b", ["a"], () => results.push("b"));
    loader.define("c", ["a"], () => results.push("c"));
    loader.define("a", [], () => results.push("a"));

    expect(loader.modules).toHaveLength(4);
    expect(loader.jobs).toBeEmpty();
    // "a" first, then "b" and "c" (order between siblings may vary), then "d" last
    expect(results[0]).toBe("a");
    expect(results[3]).toBe("d");
    expect(new Set(results.slice(1, 3))).toEqual(new Set(["b", "c"]));
});

test.tags("headless");
test("define: duplicate deps in dependency list", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    const modB = { value: "b" };
    loader.define("a", [], () => modB);
    // "b" lists "a" twice — must not cause double-counting
    loader.define("b", ["a", "a"], (req) => req("a"));

    expect(loader.modules).toHaveLength(2);
    expect(loader.modules.get("b")).toBe(modB);
    expect(loader.jobs).toBeEmpty();
});

test.tags("headless");
test("define: lazy module loaded via addJob", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    const modA = { value: "a" };
    loader.define("a", [], () => modA, true); // lazy

    // Lazy module should not be loaded yet
    expect(loader.modules.has("a")).toBe(false);
    expect(loader.jobs).toBeEmpty();

    // Trigger via addJob
    loader.addJob("a");

    expect(loader.modules.get("a")).toBe(modA);
    expect(loader.jobs).toBeEmpty();
});

test.tags("headless");
test("define: many independent modules load without O(N²) scanning", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    // 200 independent modules — all should load
    const N = 200;
    for (let i = 0; i < N; i++) {
        loader.define(`mod_${i}`, [], () => ({ id: i }));
    }

    expect(loader.modules).toHaveLength(N);
    expect(loader.jobs).toBeEmpty();
});

test.tags("headless");
test("define: chain of 100 modules resolves correctly", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    // Chain: mod_99 → mod_98 → ... → mod_1 → mod_0
    // Define in reverse order (worst case)
    const N = 100;
    for (let i = N - 1; i > 0; i--) {
        loader.define(`mod_${i}`, [`mod_${i - 1}`], () => ({ id: i }));
    }
    // Define the root last — triggers the entire chain
    loader.define("mod_0", [], () => ({ id: 0 }));

    expect(loader.modules).toHaveLength(N);
    expect(loader.jobs).toBeEmpty();

    // Verify chain resolved correctly
    for (let i = 0; i < N; i++) {
        expect(loader.modules.get(`mod_${i}`)).toEqual({ id: i });
    }
});

test.tags("headless");
test("define: failed module blocks its dependents via propagation", async () => {
    const loader = new ModuleLoader(getFixture());
    loader.debug = false;

    // a (fails) → b → c : b and c must NOT load
    // d (ok) → e : e must load
    const results = [];
    loader.define("a", [], () => {
        throw new Error("a broke");
    });
    loader.define("b", ["a"], () => results.push("b"));
    loader.define("c", ["b"], () => results.push("c"));
    loader.define("d", [], () => results.push("d"));
    loader.define("e", ["d"], () => results.push("e"));

    expect(results).toEqual(["d", "e"]);
    expect(loader.modules.has("b")).toBe(false);
    expect(loader.modules.has("c")).toBe(false);
    expect(loader.modules.has("d")).toBe(true);
    expect(loader.modules.has("e")).toBe(true);
    expect(loader.failed).toEqual(new Set(["a"]));
});

test.tags("headless");
test("define: module-started events fire in dependency order", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;

    const events = [];
    loader.bus.addEventListener("module-started", (ev) => {
        events.push(ev.detail.moduleName);
    });

    loader.define("c", ["b"], () => ({}));
    loader.define("b", ["a"], () => ({}));
    loader.define("a", [], () => ({}));

    // a must come before b, b before c
    expect(events.indexOf("a")).toBeLessThan(events.indexOf("b"));
    expect(events.indexOf("b")).toBeLessThan(events.indexOf("c"));
});

// --- registerNativeModules propagation tests ---

test.tags("headless");
test("registerNativeModules: propagates to legacy dependents", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;
    // Simulate server declaring a native module name
    loader._nativePending.add("native_a");

    // Legacy module depends on native module
    const results = [];
    loader.define("legacy_b", ["native_a"], (req) => {
        results.push("b loaded");
        return req("native_a");
    });

    // native_a not loaded yet — legacy_b should be pending
    expect(loader.modules.has("legacy_b")).toBe(false);
    expect(loader.jobs.has("legacy_b")).toBe(true);

    // Bridge registers native module
    const nativeExports = { value: "native" };
    loader.registerNativeModules({ native_a: nativeExports });

    // Now legacy_b should have loaded via _propagateLoaded
    expect(loader.modules.has("legacy_b")).toBe(true);
    expect(loader.modules.get("native_a")).toBe(nativeExports);
    expect(loader.modules.get("legacy_b")).toBe(nativeExports);
    expect(results).toEqual(["b loaded"]);
    expect(loader.jobs).toBeEmpty();
});

test.tags("headless");
test("registerNativeModules: chain propagation through multiple dependents", async () => {
    const loader = new ModuleLoader();
    loader.debug = false;
    loader._nativePending.add("native_root");

    // Chain: native_root → mid → leaf
    const order = [];
    loader.define("leaf", ["mid"], () => order.push("leaf"));
    loader.define("mid", ["native_root"], () => order.push("mid"));

    expect(loader.modules.has("mid")).toBe(false);
    expect(loader.modules.has("leaf")).toBe(false);

    loader.registerNativeModules({ native_root: { ok: true } });

    expect(loader.modules.has("mid")).toBe(true);
    expect(loader.modules.has("leaf")).toBe(true);
    expect(order).toEqual(["mid", "leaf"]);
});
