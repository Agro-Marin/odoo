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
        // Parity fixture shared with
        // odoo/addons/test_assetsbundle/tests/test_bundle_hardening.py
        // (TestBridgeShimLiterals): server-built and client-built bridges
        // must be interchangeable, so the emitted lines must match the
        // Python generator field for field.
        const source = buildBridgeModuleSource("@web/core/x", ["alpha"]);
        expect(source).toBe(
            [
                `const _m = odoo.loader.modules.get("@web/core/x");`,
                `const _d = _m?.default ?? _m;`,
                `export default _d;`,
                `export const alpha = _m?.alpha;`,
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
        expect(source).toInclude("export const valid_name = _m?.valid_name;");
        expect(source).not.toInclude("invalid-name");
        expect(source).not.toInclude("0invalid");
        // The default block is emitted exactly once, unconditionally.
        expect(source.match(/export default/g)).toHaveLength(1);
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
        // This is the bridged-consumer scenario: a bridge module snapshots
        // `export const <name> = _m?.<name>` at evaluation time. With a
        // mutable `export let` the snapshot would stay null forever; the
        // facade keeps a stable identity whose reads are live.
        let lib = null;
        const facade = makeLazyFacade(() => lib);
        const snapshot = facade; // what a bridge's `export const` captures
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
