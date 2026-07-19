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

/**
 * Capture calls to a console method for the duration of the test, restoring it
 * on cleanup. Service-startup failures are reported through the console by
 * design (see the resilience contract below), so asserting on them is how the
 * degrade-gracefully behaviour is specified.
 *
 * @param {"warn" | "error"} method
 * @returns {any[][]} captured argument lists, appended to as calls arrive
 */
function captureConsole(method) {
    const calls = [];
    const original = console[method];
    console[method] = (/** @type {any[]} */ ...args) => calls.push(args);
    after(() => {
        console[method] = original;
    });
    return calls;
}

/**
 * Create a bare env and begin its service startup.
 *
 * Deliberately NOT `makeMockEnv`: that helper conditionally awaits
 * `makeMockServer()`, which may perform a real `/web/model/get_definitions`
 * request, so the number of microtasks between the call and the first service
 * factory is an incidental scheduling detail rather than a contract. Tests that
 * observe startup mid-flight must synchronise on an observable signal (a
 * `Deferred` resolved inside the factory) instead of counting ticks.
 *
 * @returns {{ env: any, started: Promise<void> }}
 */
function startEnv() {
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    return { env, started: startServices(env) };
}

test(`can start a service`, async () => {
    registerService("test", [], () => 17);
    const env = await makeMockEnv();
    expect(env.services.test).toBe(17);
});

// Resilience contract: a service whose start() fails is logged and SKIPPED —
// it does not reject the startup pass. Left unguarded, one broken service (a
// third-party addon, say) rejects Promise.all of the whole wave, which rejects
// startServicesPromise, which fails mountComponent and blanks the entire app.
// Dependents of a failed service cascade-skip and fail at their own use site,
// the same contract as an unreachable dependency.
//
// These two tests previously asserted the opposite (`rejects.toThrow("boom")`).
// That was the pre-2026 behaviour; the guard in `_startServices`'s wave loop
// changed it deliberately, and the spec was never updated — so they had been
// failing rather than describing the intended design.

test(`a service throwing synchronously is skipped, not fatal`, async () => {
    const errors = captureConsole("error");
    registerService("ouch", [], () => {
        throw new Error("boom");
    });
    registerService("fine", [], () => "ok");

    const { env, started } = startEnv();
    await started;

    expect("ouch" in env.services).toBe(false);
    expect(env.services.fine).toBe("ok");
    expect(errors.length).toBe(1);
    expect(String(errors[0][0])).toMatch(/service "ouch" failed to start \(sync\)/);
});

test(`a service rejecting asynchronously is skipped, not fatal`, async () => {
    const errors = captureConsole("error");
    registerService("ouch", [], async () => {
        throw new Error("boom");
    });
    registerService("fine", [], () => "ok");

    const { env, started } = startEnv();
    await started;

    expect("ouch" in env.services).toBe(false);
    expect(env.services.fine).toBe("ok");
    expect(errors.length).toBe(1);
    expect(String(errors[0][0])).toMatch(/service "ouch" failed to start \(async\)/);
});

test(`a failed service does not prevent its dependents from being reported`, async () => {
    const errors = captureConsole("error");
    const warnings = captureConsole("warn");
    registerService("ouch", [], () => {
        throw new Error("boom");
    });
    registerService("needsOuch", ["ouch"], () => "never");

    const { env, started } = startEnv();
    await started;

    expect(env.services).toEqual({});
    expect(errors.length).toBe(1);
    // The dependent is cascade-skipped rather than left pending or misreported
    // as a circular dependency.
    expect(warnings.length).toBe(1);
    expect(warnings[0][0]).toMatch(/Skipped 1 service\(s\)/);
});

test(`can start an asynchronous service`, async () => {
    const deferred = new Deferred();
    const entered = new Deferred();
    registerService("test", [], async () => {
        expect.step("before");
        entered.resolve();
        const result = await deferred;
        expect.step("after");
        return result;
    });

    const { env, started } = startEnv();
    await entered; // the factory has been invoked — no tick counting
    expect.verifySteps(["before"]);

    deferred.resolve(15);
    await started;
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
    const entered1 = new Deferred();
    registerService("test1", [], () => {
        expect.step("test1");
        entered1.resolve();
        return deferred1;
    });

    registerService("test3", ["test2"], () => {
        expect.step("test3");
    });

    const { started } = startEnv();
    await entered1; // test1's factory has run; test2 is gated on it
    expect.verifySteps(["test1"]);

    // Resolving the DEPENDENT's deferred must not unlock anything: test2 has
    // not started yet, so nothing can observe it.
    deferred2.resolve();
    await tick();
    expect.verifySteps([]);

    // Resolving the dependency unlocks the rest of the chain.
    deferred1.resolve();
    await started;
    expect.verifySteps(["test2", "test3"]);
});

test(`can start two independant asynchronous services in parallel`, async () => {
    const deferred1 = new Deferred();
    const entered1 = new Deferred();
    registerService("test1", [], () => {
        expect.step("test1");
        entered1.resolve();
        return deferred1;
    });

    const deferred2 = new Deferred();
    const entered2 = new Deferred();
    registerService("test2", [], () => {
        expect.step("test2");
        entered2.resolve();
        return deferred2;
    });

    registerService("test3", ["test1", "test2"], () => {
        expect.step("test3");
    });

    const { started } = startEnv();
    // Both dependency-free services belong to the same wave and are invoked
    // together, before either resolves.
    await Promise.all([entered1, entered2]);
    expect.verifySteps(["test1", "test2"]);

    // test3 needs BOTH: resolving only one must not unlock it.
    deferred1.resolve();
    await tick();
    expect.verifySteps([]);

    deferred2.resolve();
    await started;
    expect.verifySteps(["test3"]);
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

test(`a queued startup pass runs even if the in-flight pass rejects`, async () => {
    // Re-entrancy guard regression: while one _startServices pass is
    // in-flight, an independent second pass serializes behind it via
    // startServicesPromise. If the first pass rejects (a service.start()
    // throws), the second, independent pass must still run to completion and
    // start its own services — it must not inherit the first pass's unrelated
    // rejection nor be silently cancelled.
    const errors = captureConsole("error");
    const env = makeEnv();
    after(() => env.disposeServiceRegistryListener?.());
    // "boom" fails on its first start (poisoning the in-flight pass) and
    // recovers on a later pass, so we can assert the queued pass re-ran.
    const deferredBoom = new Deferred();
    const enteredBoom = new Deferred();
    let boomStarts = 0;
    registerService("boom", [], () => {
        boomStarts++;
        enteredBoom.resolve();
        return boomStarts === 1 ? deferredBoom : "recovered";
    });

    // First (in-flight) pass: captures {boom} and suspends on boom's deferred.
    const p1 = ensureServicesStarted(env);
    await enteredBoom;

    // Second (queued) pass: registered after p1 captured its work, so its
    // "good" service belongs solely to this independent pass.
    registerService("good", [], () => "g");
    const p2 = ensureServicesStarted(env);

    // Per the resilience contract, boom's rejection is logged and skipped
    // rather than rejecting the in-flight pass — but the invariant under test
    // is unchanged: the queued, independent pass must still run to completion
    // and start its own services.
    deferredBoom.reject(new Error("boom"));
    await p1;
    await p2;

    expect(env.services.good).toBe("g");
    expect(env.services.boom).toBe("recovered");
    expect(errors.length).toBe(1);
    expect(String(errors[0][0])).toMatch(/service "boom" failed to start \(async\)/);
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

    const entered = new Deferred();
    registerService("test", [], async (env) => {
        expect.step("before");
        env.isReady.then(() => {
            expect.step("env ready");
        });
        entered.resolve();

        const result = await deferred;
        expect.step("after");
        return result;
    });

    const { started } = startEnv();
    await entered; // the factory has been invoked — no tick counting
    expect.verifySteps(["before"]);

    deferred.resolve();
    await started;
    // `isReady` resolves on the SERVICES_LOADED bus event, which startServices
    // triggers only after every wave has settled — hence strictly after "after".
    await Promise.resolve();
    expect.verifySteps(["after", "env ready"]);
});
