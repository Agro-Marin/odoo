// @ts-check

import { after, beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { Deferred, tick } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    allowTranslations,
    clearRegistry,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import {
    _resetCascadeWarningCache,
    ensureServicesStarted,
    makeEnv,
    mountComponent,
    startServices,
} from "@web/env";

describe.current.tags("headless");

const servicesRegistry = registry.category("services");

beforeEach(() => {
    clearRegistry(servicesRegistry);
    // env.js dedupes cascade-skip warnings by (skipped, missing) tuple
    // for the page's lifetime; clear that between tests so each test
    // starts with a clean dedup cache and the existing test assertions
    // on warning count remain deterministic regardless of test order.
    _resetCascadeWarningCache();
});

/**
 * @param {string} name
 * @param {string[]} dependencies
 * @param {(env: import("@web/env").OdooEnv, dependencies: Record<string, any>) => any} factory
 */
function registerService(name, dependencies, factory) {
    servicesRegistry.add(name, {
        dependencies,
        start: factory,
    });
}

test(`can start a service`, async () => {
    registerService("test", [], () => 17);
    const env = await makeMockEnv();
    expect(env.services.test).toBe(17);
});

test(`crashing service start causes startService to crash`, async () => {
    registerService("ouch", [], () => {
        throw new Error("boom");
    });
    await expect(makeMockEnv()).rejects.toThrow("boom");
});

test(`crashing async service start causes startService to crash`, async () => {
    registerService("ouch", [], async () => {
        throw new Error("boom");
    });
    await expect(makeMockEnv()).rejects.toThrow("boom");
});

test(`can start an asynchronous service`, async () => {
    const deferred = new Deferred();
    registerService("test", [], async () => {
        expect.step("before");
        const result = await deferred;
        expect.step("after");
        return result;
    });

    const envCreationPromise = makeMockEnv();
    await tick(); // wait for startServices
    expect.verifySteps(["before"]);

    deferred.resolve(15);
    const env = await envCreationPromise;
    expect.verifySteps(["after"]);
    expect(env.services.test).toBe(15);
});

test(`can start a service with a dependency`, async () => {
    registerService("aang", ["appa"], () => expect.step("aang"));
    registerService("appa", [], () => expect.step("appa"));

    await makeMockEnv();
    expect.verifySteps(["appa", "aang"]);
});

test(`get an object containing dependencies as second arg`, async () => {
    registerService("aang", ["appa"], (_, dependencies) => {
        expect.step("aang");
        expect(dependencies).toEqual({ appa: "flying bison" });
    });
    registerService("appa", [], () => {
        expect.step("appa");
        return "flying bison";
    });

    await makeMockEnv();
    expect.verifySteps(["appa", "aang"]);
});

test(`can start two sequentially dependant asynchronous services`, async () => {
    const deferred2 = new Deferred();
    registerService("test2", ["test1"], () => {
        expect.step("test2");
        return deferred2;
    });

    const deferred1 = new Deferred();
    registerService("test1", [], () => {
        expect.step("test1");
        return deferred1;
    });

    registerService("test3", ["test2"], () => {
        expect.step("test3");
    });

    const envCreationPromise = makeMockEnv();
    await tick();
    expect.verifySteps(["test1"]);

    deferred2.resolve();
    await tick();
    expect.verifySteps([]);

    deferred1.resolve();
    await tick();
    expect.verifySteps(["test2", "test3"]);

    await envCreationPromise;
});

test(`can start two independant asynchronous services in parallel`, async () => {
    const deferred1 = new Deferred();
    registerService("test1", [], () => {
        expect.step("test1");
        return deferred1;
    });

    const deferred2 = new Deferred();
    registerService("test2", [], () => {
        expect.step("test2");
        return deferred2;
    });

    registerService("test3", ["test1", "test2"], () => {
        expect.step("test3");
    });

    const envCreationPromise = makeMockEnv();
    await tick();
    expect.verifySteps(["test1", "test2"]);

    deferred1.resolve();
    await tick();
    expect.verifySteps([]);

    deferred2.resolve();
    await tick();
    expect.verifySteps(["test3"]);

    await envCreationPromise;
});

test(`startServices: skips services with unreachable deps and warns (no throw)`, async () => {
    // Behavior change (2026-05-22): previously threw on missing deps. Now
    // skips (a provider registering after its dependent happens in both lazy
    // test bundles and production ESM microtask ordering) so the run
    // continues; a late-arriving provider recovers on the next
    // startServices pass, a dep that never arrives fails at its use site.
    // Callers needing a lazy bundle's service synchronously should await
    // ensureServicesStarted after loadBundle instead of relying on this.
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    registerService("b", ["a"], () => "b");

    const warnings = [];
    const originalWarn = console.warn;
    console.warn = (...args) => warnings.push(args);
    after(() => {
        console.warn = originalWarn;
    });

    await startServices(env);
    // "b" was skipped because "a" was never registered.
    expect(env.services).toEqual({});
    expect(warnings.length).toBe(1);
    expect(warnings[0][0]).toMatch(/Skipped 1 service\(s\)/);
    expect(warnings[0][0]).toMatch(/\bb\b/);

    // Registering the missing dep and re-calling startServices recovers:
    // both services start.
    registerService("a", [], () => "a");
    await startServices(env);
    expect(env.services).toEqual({ a: "a", b: "b" });
});

test(`ensureServicesStarted: starts late-registered services without a registry listener`, async () => {
    // The lazy-bundle scenario (addSpreadsheetActionLazyLoader): services
    // registered after startup must be guaranteed started by the time
    // ensureServicesStarted resolves, independently of the background
    // registry UPDATE listener — which is disposed here on purpose.
    const env = makeEnv();
    await startServices(env);
    env.disposeServiceRegistryListener();
    registerService("provider", [], () => "p");
    registerService("consumer", ["provider"], (_env, deps) => `${deps.provider}-c`);
    expect(env.services).toEqual({});

    await ensureServicesStarted(env);
    expect(env.services).toEqual({ provider: "p", consumer: "p-c" });

    // Idempotent: a second pass with nothing new to start is a no-op.
    await ensureServicesStarted(env);
    expect(env.services).toEqual({ provider: "p", consumer: "p-c" });
});

test(`startServices: cascade-skips transitive consumers when a dep is missing`, async () => {
    // If "a" is missing, "b" (needs a) is skipped, and "c" (needs b)
    // is also skipped — the cascade iterates to a fixpoint so the
    // circular-dep check below the cascade is not falsely tripped.
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    registerService("c", ["b"], () => "c");
    registerService("b", ["a"], () => "b");

    const warnings = [];
    const originalWarn = console.warn;
    console.warn = (...args) => warnings.push(args);
    after(() => {
        console.warn = originalWarn;
    });

    await startServices(env);
    expect(env.services).toEqual({});
    expect(warnings.length).toBe(1);
    expect(warnings[0][0]).toMatch(/Skipped 2 service\(s\)/);
});

test(`registry UPDATE while missing-dep leftovers exist starts the new service (no false circular throw)`, async () => {
    // The old implementation shared one ``toStart`` Map between the UPDATE
    // listener and in-flight passes: a startable service landing while
    // cascade-skip leftovers existed could reach the post-wave check and be
    // misreported as "Circular service dependency detected". The listener
    // now always schedules a fresh pass, and the final check only throws
    // when findDependencyCycle actually finds a cycle.
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    // Leftover state: "b" depends on a never-registered "a".
    registerService("b", ["a"], () => "b");

    const warnings = [];
    const originalWarn = console.warn;
    console.warn = (...args) => warnings.push(args);
    after(() => {
        console.warn = originalWarn;
    });

    await startServices(env);
    expect(env.services).toEqual({});

    // A fully-satisfiable service registered afterwards must start via the
    // UPDATE listener without throwing.
    registerService("standalone", [], () => "s");
    await tick();
    await tick();
    expect(env.services).toEqual({ standalone: "s" });
});

test(`startServices: still throws on genuine circular dependency`, async () => {
    // Cascade-skip removes services with truly missing deps; anything
    // remaining in toStart must have all deps registered yet failed to
    // make progress — that's a circular dependency, which stays a hard
    // error in all environments (programming bug).
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    registerService("x", ["y"], () => "x");
    registerService("y", ["x"], () => "y");

    await expect(startServices(env)).rejects.toThrow(
        /Circular service dependency detected/,
    );
});

/**
 * Capture console.warn calls during ``body`` and return them.  Restores
 * the original function on completion.  Async-aware via try/finally.
 */
async function captureWarns(body) {
    const captured = [];
    const original = console.warn;
    console.warn = (...args) => captured.push(args);
    try {
        await body();
    } finally {
        console.warn = original;
    }
    return captured;
}

test(`debug-mode dep validator: warns when a service is added with a missing dep`, async () => {
    // Early-detection sibling to the env.js cascade-skip: warns at
    // registration time (not waiting for startServices) so the dev sees
    // the bug at the point of their edit. Microtask-deferred so sibling
    // synchronous adds can land first (matches _startServices convention).
    patchWithCleanup(odoo, { debug: "1" });

    const warns = await captureWarns(async () => {
        registerService("orphan", ["never-registered"], () => "orphan");
        await tick();
    });
    expect(warns.length).toBe(1);
    expect(warns[0][0]).toMatch(/Service "orphan" declares missing dependencies/);
    expect(warns[0][0]).toMatch(/never-registered/);
});

test(`debug-mode dep validator: silent when provider registers in same microtask`, async () => {
    // Sibling synchronous registrations land before the microtask-
    // deferred check fires.  This is the common case in production
    // bundles where esbuild concatenates module evaluation order, so
    // the validator must not warn.
    patchWithCleanup(odoo, { debug: "1" });

    const warns = await captureWarns(async () => {
        registerService("consumer", ["provider"], () => "consumer");
        registerService("provider", [], () => "provider");
        await tick();
    });
    expect(warns.length).toBe(0);
});

test(`debug-mode dep validator: silent in production (odoo.debug is empty)`, async () => {
    // Production deliberately stays quiet: the cascade-skip in
    // _startServices is the source of truth for runtime behavior,
    // and a per-add warning would generate noise in user environments
    // where third-party addons may legitimately load deps later.
    patchWithCleanup(odoo, { debug: "" });

    const warns = await captureWarns(async () => {
        registerService("orphan", ["never-registered"], () => "orphan");
        await tick();
    });
    expect(warns.length).toBe(0);
});

test(`cascade-skip warning: deduped across startServices calls with the same shape`, async () => {
    // The dedup keys on (sorted-skipped, sorted-missing) so 327
    // identical misconfigurations across @web/core tests collapse to
    // one warning per page lifetime, not one per test.
    registerService("dedup_b", ["dedup_a"], () => "dedup_b");

    const env1 = makeEnv();
    after(() => env1.disposeServiceRegistryListener?.());
    const env2 = makeEnv();
    after(() => env2.disposeServiceRegistryListener?.());

    const warns = await captureWarns(async () => {
        await startServices(env1); // 1st call: warns
        await startServices(env2); // 2nd call, same shape: silent
    });
    expect(warns.length).toBe(1);
    expect(warns[0][0]).toMatch(/dedup_b/);
});

test(`cascade-skip warning: re-fires when the shape changes`, async () => {
    // A genuinely new misconfiguration (different skipped service or
    // different missing dep) gets its own warning, so the dedup never
    // silences a NEW bug.
    registerService("shape_b", ["shape_a"], () => "shape_b");

    const env1 = makeEnv();
    after(() => env1.disposeServiceRegistryListener?.());
    const warns = await captureWarns(async () => {
        await startServices(env1); // 1st shape: warns

        // Now register a *different* missing-dep relationship.
        registerService("shape_d", ["shape_c"], () => "shape_d");
        const env2 = makeEnv();
        after(() => env2.disposeServiceRegistryListener?.());
        await startServices(env2); // 2nd shape: warns (different skipped+missing)
    });
    expect(warns.length).toBe(2);
    expect(warns[0][0]).toMatch(/shape_b/);
    expect(warns[1][0]).toMatch(/shape_d/);
});

test(`startServices: waits for all synchronous code before attempting to start services`, async () => {
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    registerService("b", ["a"], () => "b");

    const serviceStartingPromise = startServices(env);
    // Dependency added in the same microtick doesn't cause startServices to throw even if it was added after the call
    // (eg, a module is defined after main.js)
    registerService("a", [], () => "a");

    await serviceStartingPromise;
    expect(env.services).toEqual({ a: "a", b: "b" });
});

test(`mountComponent creates an env and sets the application as root when no env is provided`, async () => {
    allowTranslations();
    registerService("my_service", [], () => "a");

    class Root extends Component {
        static template = xml`Root`;
        static props = ["*"];
    }
    const app = await mountComponent(Root, getFixture());
    after(() => {
        delete odoo.__WOWL_DEBUG__;
        // mountComponent creates its own env (isRoot=true) + startServices,
        // attaching a registry UPDATE listener. It bypasses makeMockEnv so
        // the global afterEach cleanup doesn't see it — dispose explicitly
        // to avoid leaking into the next test.
        app.env.disposeServiceRegistryListener?.();
    });
    const { env } = app;
    expect(env.services).toEqual({ my_service: "a" });
    expect(odoo.__WOWL_DEBUG__).toEqual({ root: app.root.component });
    expect(getFixture()).toHaveText("Root");
});

test(`mountComponent uses the env when provided and doesn't start the services`, async () => {
    allowTranslations();
    registerService("my_service", [], () => {
        expect.step("starting myService");
        return "a";
    });

    const env = makeEnv();
    expect.verifySteps([]);
    await startServices(env);
    after(() => env.disposeServiceRegistryListener?.());
    expect.verifySteps(["starting myService"]);

    class Root extends Component {
        static template = xml`Root`;
        static props = ["*"];
    }

    const app = await mountComponent(Root, getFixture(), { env });
    expect.verifySteps([]);
    expect(app.env.services).toBe(env.services);
    expect(odoo.__WOWL_DEBUG__).toBe(undefined);
    expect(getFixture()).toHaveText("Root");
});

test(`mountComponent: can pass props to the root component`, async () => {
    class Root extends Component {
        static template = xml`<t t-esc="props.text"/>`;
        static props = ["*"];
    }

    const app = await mountComponent(Root, getFixture(), {
        props: { text: "text from props" },
    });
    after(() => {
        delete odoo.__WOWL_DEBUG__;
        app.env.disposeServiceRegistryListener?.();
    });
    expect(getFixture()).toHaveText("text from props");
});

test(`env.isReady is resolved after services are loaded`, async () => {
    const deferred = new Deferred();

    registerService("test", [], async (env) => {
        expect.step("before");
        env.isReady.then(() => {
            expect.step("env ready");
        });

        const result = await deferred;
        expect.step("after");
        return result;
    });

    const envCreationPromise = makeMockEnv();
    await tick(); // wait for startServices
    expect.verifySteps(["before"]);

    deferred.resolve();
    await envCreationPromise;
    expect.verifySteps(["after", "env ready"]);
});
