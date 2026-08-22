// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    buildBridgeModuleSource,
    isLoaderBridgeUrl,
    makeLazyFacade,
    specToModuleUrl,
    toDataModuleUrl,
} from "@web/core/module_bridge";

describe.current.tags("headless");

describe("bridge source generation", () => {
    test("emits the exact shape of the Python generator (_bridge_shim_source)", () => {
        const source = buildBridgeModuleSource("@web/core/x", ["alpha"]);
        expect(source).toBe(
            [
                `let _d, _e0;`,
                `function _s() {`,
                `  const _m = odoo.loader.modules.get("@web/core/x");`,
                `  if (_m === undefined) { return; }`,
                `  _d = _m.default ?? _m;`,
                `  _e0 = _m.alpha;`,
                `  odoo.loader.bus.removeEventListener("registered", _s);`,
                `}`,
                `_s();`,
                `odoo.loader.bus.addEventListener("registered", _s);`,
                `export { _d as default, _e0 as alpha };`,
            ].join("\n"),
        );
    });

    test("skips 'default' and non-identifier export names", () => {
        const source = buildBridgeModuleSource("@web/core/x", [
            "default",
            "valid_name",
            "invalid-name",
            "0invalid",
        ]);
        expect(source).toInclude("_e0 = _m.valid_name;");
        expect(source).toInclude("_e0 as valid_name");
        expect(source).not.toInclude("invalid-name");
        expect(source).not.toInclude("0invalid");
        expect(source).not.toInclude("export default");
        expect(source.match(/_d as default/g)).toHaveLength(1);
    });

    test("a producer that registers later still reaches the bridge", async () => {
        const spec = "@probe/registers/late";
        const mod = await import(
            toDataModuleUrl(buildBridgeModuleSource(spec, ["alpha", "beta"]))
        );
        expect(mod.alpha).toBe(undefined);
        expect(mod.default).toBe(undefined);

        odoo.loader.registerNativeModules({ [spec]: { alpha: 42, beta: "hi" } });

        expect(mod.alpha).toBe(42);
        expect(mod.beta).toBe("hi");
        expect(mod.default).toEqual({ alpha: 42, beta: "hi" });
    });

    test("specifier is JSON-quoted (script-safe)", () => {
        const source = buildBridgeModuleSource(`@web/we"ird`, []);
        expect(source).toInclude(JSON.stringify(`@web/we"ird`));
    });

    test("toDataModuleUrl/specToModuleUrl/isLoaderBridgeUrl helpers", () => {
        expect(toDataModuleUrl("export default 1;")).toBe(
            `data:text/javascript,${encodeURIComponent("export default 1;")}`,
        );
        expect(specToModuleUrl("@web/core/registry")).toBe(
            "/web/static/src/core/registry.js",
        );
        expect(specToModuleUrl("not-scoped/foo")).toBe(null);
        expect(specToModuleUrl("@web/../evil")).toBe(null);
        expect(isLoaderBridgeUrl("data:text/javascript,foo")).toBe(true);
        expect(isLoaderBridgeUrl("/web/assets/esm/bridges/abc.js")).toBe(true);
        expect(isLoaderBridgeUrl("/web/static/src/core/registry.js")).toBe(false);
    });
});

describe("makeLazyFacade (bridge-safe lazy exports)", () => {
    test("a snapshot taken before load forwards to the value loaded later", () => {
        let lib = null;
        const facade = makeLazyFacade(() => lib);
        const snapshot = facade;
        expect(snapshot.anything).toBe(undefined);
        lib = { greet: (/** @type {string} */ name) => `hello ${name}` };
        expect(snapshot).toBe(facade);
        expect(snapshot.greet("world")).toBe("hello world");
    });

    test("constructable facade forwards construction, statics and instanceof", () => {
        let lib = null;
        const Facade = makeLazyFacade(() => lib, { constructable: true });
        expect(typeof Facade).toBe("function");
        class RealChart {
            static defaults = { animation: true };
            static register(/** @type {any} */ ...items) {
                return items.length;
            }
            constructor(/** @type {any} */ config) {
                this.config = config;
            }
        }
        lib = RealChart;
        const instance = new Facade({ type: "bar" });
        expect(instance.config).toEqual({ type: "bar" });
        expect(instance).toBeInstanceOf(RealChart);
        expect(instance).toBeInstanceOf(Facade);
        expect(Facade.defaults.animation).toBe(true);
        expect(Facade.register("a", "b")).toBe(2);
    });

    test("namespace facade supports has/keys/spread once loaded", () => {
        let lib = null;
        const facade = makeLazyFacade(() => lib);
        lib = { Calendar: class {}, version: "7" };
        expect("Calendar" in facade).toBe(true);
        expect(Object.keys(facade).sort()).toEqual(["Calendar", "version"]);
        expect({ ...facade }.version).toBe("7");
    });

    test("writes forward to the loaded value", () => {
        /** @type {any} */
        let lib = null;
        const facade = makeLazyFacade(() => lib);
        lib = {};
        facade.workerSrc = "/some/worker.js";
        expect(lib.workerSrc).toBe("/some/worker.js");
    });

    test("facade is not thenable (safe to resolve from an async loader)", async () => {
        let lib = null;
        const facade = makeLazyFacade(() => lib);
        expect(facade.then).toBe(undefined);
        lib = { value: 42 };
        const awaited = await Promise.resolve(facade);
        expect(awaited).toBe(facade);
        expect(awaited.value).toBe(42);
    });
});

describe("bridge source with awkward export names", () => {
    test("a reserved word is re-exported under an alias, not `export const`", () => {
        const source = buildBridgeModuleSource("@web/x", ["foo", "class", "await"]);
        expect(source).not.toInclude("export const class");
        expect(source).toInclude("_m.class");
        expect(source).toInclude("as class");
        expect(source).toInclude("as await");
        expect(source).toInclude("as foo");
    });

    test("the generated source parses as a module", async () => {
        const source = buildBridgeModuleSource("@web/x", [
            "ok",
            "class",
            "new",
            "yield",
            "default",
            "1invalid",
        ]);
        odoo.loader.modules.set("@web/x", { ok: 1, class: 2 });
        const mod = await import(toDataModuleUrl(source));
        expect(mod.ok).toBe(1);
        expect(mod["class"]).toBe(2);
        expect("1invalid" in mod).toBe(false);
    });
});
