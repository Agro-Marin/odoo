// @odoo-module ignore

/** @module @web/module_loader - Bootstrap module loader that resolves dependency graphs and defines odoo.loader */

//-----------------------------------------------------------------------------
// Odoo Web Bootstrap Code
//-----------------------------------------------------------------------------

(function (odoo) {
    "use strict";

    // Capture native timers BEFORE any mock can replace them.
    // This runs as the very first script in the bundle, so
    // globalThis.setTimeout is guaranteed to be the real browser function.
    // Hoot's test runner reads these to implement test timeouts that fire
    // even when timers are mocked/frozen.
    odoo.__nativeTimers = {
        setTimeout: globalThis.setTimeout.bind(globalThis),
        clearTimeout: globalThis.clearTimeout.bind(globalThis),
    };

    if (odoo.loader) {
        // Allows for duplicate calls to `module_loader`: only the first one is
        // executed.
        return;
    }

    /**
     * Resolves and executes a dependency graph of JavaScript modules.
     *
     * Uses dependency-counting with reverse-edge propagation: when a module
     * loads, all its dependents have their pending count decremented, and any
     * that reach zero are immediately queued for execution.
     *
     * Complexity: O(V + E) where V = modules, E = total dependency edges.
     */
    class ModuleLoader {
        /** @type {OdooModuleLoader["bus"]} */
        bus = new EventTarget();
        /** @type {OdooModuleLoader["checkErrorProm"]} */
        checkErrorProm = null;
        /** @type {OdooModuleLoader["factories"]} */
        factories = new Map();
        /** @type {OdooModuleLoader["failed"]} */
        failed = new Set();
        /**
         * Pending module names. Kept as a real Set for backward compatibility
         * with subclasses (e.g. ModuleSetLoader) that mutate it directly.
         * @type {OdooModuleLoader["jobs"]}
         */
        jobs = new Set();
        /** @type {OdooModuleLoader["modules"]} */
        modules = new Map();

        // --- O(V+E) dependency resolution state ---

        /** Count of unmet deps per pending module. @type {Map<string, number>} */
        _pendingDeps = new Map();
        /** Reverse graph: dep name → modules waiting on it. @type {Map<string, Set<string>>} */
        _dependents = new Map();
        /** Modules with all deps met, ready to execute. @type {string[]} */
        _readyQueue = [];
        /**
         * Native module names declared by the server.  Used to suppress
         * "missing dependency" errors for modules that will be registered
         * by the post-bundle bridge script.
         * @type {Set<string>}
         */
        _nativePending = new Set();

        /**
         * @param {HTMLElement} [root]
         */
        constructor(root) {
            this.root = root;

            const strDebug = new URLSearchParams(location.search).get("debug");
            this.debug = Boolean(strDebug && strDebug !== "0");

            // Absorb any native module names declared so far.  Multiple
            // bundles may push names into the array before the loader runs,
            // so we consume all of them.  Later bundles that push after this
            // constructor will be consumed by _consumeNativeNames() which is
            // called from define().
            this._consumeNativeNames();
        }

        /**
         * Consume any native module names that have been pushed into
         * ``odoo.__native_module_names__`` since the last call.
         * Multiple bundles may push into this shared array at different
         * points in time (each bundle's names-declaration script runs
         * before its own deferred bundle script).
         */
        _consumeNativeNames() {
            const arr = odoo.__native_module_names__;
            if (arr && arr.length) {
                for (const name of arr) {
                    this._nativePending.add(name);
                }
                arr.length = 0; // clear without replacing the reference
            }
        }

        /** @type {OdooModuleLoader["addJob"]} */
        addJob(name) {
            this._enqueue(name);
            this.startModules();
        }

        /** @type {OdooModuleLoader["define"]} */
        define(name, deps, factory, lazy = false) {
            // Pick up any newly-declared native module names from later
            // bundles so they're in _nativePending before we enqueue.
            this._consumeNativeNames();
            if (typeof name !== "string") {
                throw new Error(`Module name should be a string, got: ${String(name)}`);
            }
            if (!Array.isArray(deps)) {
                throw new Error(
                    `Module dependencies should be a list of strings, got: ${String(deps)}`,
                );
            }
            if (typeof factory !== "function") {
                throw new Error(
                    `Module factory should be a function, got: ${String(factory)}`,
                );
            }
            if (this.factories.has(name) || this.modules.has(name) || this._nativePending.has(name)) {
                return; // Ignore: already defined, loaded, or pending native ESM
            }
            this.factories.set(name, {
                deps,
                fn: factory,
                ignoreMissingDeps: globalThis.__odooIgnoreMissingDependencies,
            });
            if (!lazy) {
                this.addJob(name);
                // Defer error checking to a microtask so all synchronous
                // defines() are batched.  When native modules are still
                // pending (bridge hasn't run yet), skip the check entirely
                // — registerNativeModules() will trigger it after the
                // bridge resolves the remaining deps.
                if (!this._nativePending.size) {
                    this.checkErrorProm ||= Promise.resolve()
                        .then(() => {
                            this.checkErrorProm = null;
                            return this.reportErrors(this.findErrors());
                        })
                        .catch(() => {});
                }
            }
        }

        /**
         * Register a module for dependency tracking and enqueue if ready.
         *
         * Populates the reverse-edge graph so that when dependencies load,
         * this module's pending count is decremented in O(1).
         * Handles duplicate deps correctly via Set membership check.
         *
         * @param {string} name
         */
        _enqueue(name) {
            if (this.modules.has(name) || this._pendingDeps.has(name)) {
                return;
            }
            const factory = this.factories.get(name);
            if (!factory) {
                return;
            }
            this.jobs.add(name);
            let pending = 0;
            for (const dep of factory.deps) {
                if (!this.modules.has(dep)) {
                    let waiters = this._dependents.get(dep);
                    if (!waiters) {
                        waiters = new Set();
                        this._dependents.set(dep, waiters);
                    }
                    // Dedup: only count each unique dep once per module
                    if (!waiters.has(name)) {
                        waiters.add(name);
                        pending++;
                    }
                }
            }
            this._pendingDeps.set(name, pending);
            if (pending === 0) {
                this._readyQueue.push(name);
            }
        }

        /** @type {OdooModuleLoader["findErrors"]} */
        findErrors(moduleNames) {
            moduleNames ||= this.jobs;

            /** @type {Record<string, Iterable<string>>} */
            const dependencyGraph = Object.create(null);
            /** @type {Set<string>} */
            const missing = new Set();
            /** @type {Set<string>} */
            const unloaded = new Set();

            for (const moduleName of moduleNames) {
                const factory = this.factories.get(moduleName);
                if (!factory) {
                    continue;
                }
                const { deps, ignoreMissingDeps } = factory;

                dependencyGraph[moduleName] = deps;

                if (ignoreMissingDeps) {
                    continue;
                }

                unloaded.add(moduleName);
                for (const dep of deps) {
                    if (!this.factories.has(dep) && !this._nativePending.has(dep)) {
                        missing.add(dep);
                    }
                }
            }

            const cycle = this._findCycle(dependencyGraph);
            const errors = {};
            if (cycle) {
                errors.cycle = cycle;
            }
            if (this.failed.size) {
                errors.failed = this.failed;
            }
            if (missing.size) {
                errors.missing = missing;
            }
            if (unloaded.size) {
                errors.unloaded = unloaded;
            }
            return errors;
        }

        /**
         * O(V+E) cycle detection using DFS with 3-color marking.
         *
         * White (unvisited) → Gray (in current DFS path) → Black (fully explored).
         * A back-edge to a Gray node indicates a cycle. The cycle path is
         * extracted from the explicit DFS stack.
         *
         * Replaces the previous implementation that copied the visited Set on
         * every recursive call (O(V² × E) worst case).
         *
         * @param {Record<string, Iterable<string>>} graph
         * @returns {string | null} human-readable cycle string, or null
         */
        _findCycle(graph) {
            const GRAY = 1;
            const BLACK = 2;
            const color = Object.create(null);
            const stack = [];

            const dfs = (node) => {
                color[node] = GRAY;
                stack.push(node);
                for (const dep of graph[node] || []) {
                    if (!(dep in graph)) {
                        continue;
                    }
                    if (color[dep] === GRAY) {
                        // Back-edge: extract the cycle from the DFS stack
                        return [...stack.slice(stack.indexOf(dep)), dep]
                            .map((j) => `"${j}"`)
                            .join(" => ");
                    }
                    if (!color[dep]) {
                        const found = dfs(dep);
                        if (found) {
                            return found;
                        }
                    }
                }
                stack.pop();
                color[node] = BLACK;
                return null;
            };

            for (const node of Object.keys(graph)) {
                if (!color[node]) {
                    const found = dfs(node);
                    if (found) {
                        return found;
                    }
                }
            }
            return null;
        }

        /** @type {OdooModuleLoader["reportErrors"]} */
        async reportErrors(errors) {
            if (!Object.keys(errors).length) {
                return;
            }

            if (errors.failed) {
                console.error(
                    "The following modules failed to load because of an error:",
                    [...errors.failed],
                );
            }
            if (errors.missing) {
                console.error(
                    "The following modules are needed by other modules but have not been defined, they may not be present in the correct asset bundle:",
                    [...errors.missing],
                );
            }
            if (errors.cycle) {
                console.error(
                    "The following modules could not be loaded because they form a dependency cycle:",
                    errors.cycle,
                );
            }
            if (errors.unloaded) {
                console.error(
                    "The following modules could not be loaded because they have unmet dependencies, this is a secondary error which is likely caused by one of the above problems:",
                    [...errors.unloaded],
                );
            }

            const document = this.root?.ownerDocument || globalThis.document;
            if (document.readyState === "loading") {
                await new Promise((resolve) =>
                    document.addEventListener("DOMContentLoaded", resolve),
                );
            }

            if (this.debug) {
                const style = document.createElement("style");
                style.className = "o_module_error_banner";
                style.textContent = `
                    body::before {
                        font-weight: bold;
                        content: "An error occurred while loading javascript modules, you may find more information in the devtools console";
                        position: fixed;
                        left: 0;
                        bottom: 0;
                        z-index: 100000000000;
                        background-color: #C00;
                        color: #DDD;
                    }
                `;
                document.head.appendChild(style);
            }
        }

        /** @type {OdooModuleLoader["startModules"]} */
        startModules() {
            while (this._readyQueue.length) {
                const name = this._readyQueue.pop();
                if (this.modules.has(name)) {
                    continue;
                }
                try {
                    this.startModule(name);
                } catch (error) {
                    // Log but don't re-throw: one broken module must not prevent
                    // the rest of the bundle from loading. The module is already
                    // in this.failed and will be reported by findErrors().
                    console.error(error.message, error.cause);
                }
            }
        }

        /**
         * Propagate: a module has loaded — decrement pending count for all
         * dependents, enqueuing any that reach zero unmet deps.
         *
         * Shared by startModule() and registerNativeModules() to avoid
         * duplicated propagation logic.
         *
         * @param {string} name
         */
        _propagateLoaded(name) {
            const waiters = this._dependents.get(name);
            if (waiters) {
                for (const waiter of waiters) {
                    const remaining = this._pendingDeps.get(waiter);
                    if (remaining !== undefined) {
                        const count = remaining - 1;
                        this._pendingDeps.set(waiter, count);
                        if (count === 0) {
                            this._readyQueue.push(waiter);
                        }
                    }
                }
                this._dependents.delete(name);
            }
        }

        /** @type {OdooModuleLoader["startModule"]} */
        startModule(name) {
            /** @type {(dependency: string) => OdooModule} */
            const require = (dependency) => this.modules.get(dependency);
            this.jobs.delete(name);
            this._pendingDeps.delete(name);
            const factory = this.factories.get(name);
            /** @type {OdooModule | null} */
            let module;
            try {
                module = factory.fn(require);
            } catch (error) {
                this.failed.add(name);
                throw new Error(`Error while loading "${name}"`, {
                    cause: error,
                });
            }
            this.modules.set(name, module);
            this._propagateLoaded(name);

            this.bus.dispatchEvent(
                new CustomEvent("module-started", {
                    detail: { moduleName: name, module },
                }),
            );
            return module;
        }

        /**
         * Register native ESM modules loaded by the post-bundle bridge.
         *
         * Called from the bridge ``<script type="module">`` which executes
         * after the legacy bundle in the deferred queue.  For each module:
         * 1. Stores its exports in ``this.modules`` (makes require() work)
         * 2. Propagates to dependents (decrements their pending count)
         * 3. Queues any dependents that reach zero unmet deps
         *
         * Finally calls ``startModules()`` to execute the newly-ready
         * legacy modules.  All of this happens before DOMContentLoaded,
         * so the app sees a fully-loaded module graph.
         *
         * @param {Record<string, object>} modules  specifier → namespace object
         */
        registerNativeModules(modules) {
            for (const [name, mod] of Object.entries(modules)) {
                this._nativePending.delete(name);
                this.modules.set(name, mod);
                this.jobs.delete(name);
                this._propagateLoaded(name);
            }
            this.startModules();
            // After all native modules are registered and dependents
            // resolved, check for any remaining errors (real missing deps,
            // cycles, etc.).  Schedule as microtask to batch with any
            // defines triggered by startModules().
            if (!this._nativePending.size && this.jobs.size) {
                this.checkErrorProm ||= Promise.resolve()
                    .then(() => {
                        this.checkErrorProm = null;
                        return this.reportErrors(this.findErrors());
                    })
                    .catch(() => {});
            }
        }
    }

    const loader = new ModuleLoader();
    odoo.define = loader.define.bind(loader);
    odoo.loader = loader;

    if (odoo.debug && !loader.debug) {
        // remove debug mode if not explicitly set in url
        odoo.debug = "";
    }

    // Signal for native ESM bridge shims (data: URI modules) that the
    // legacy bundle has finished all synchronous define() calls.
    //
    // Bridge shims use `await odoo.__legacyReady` before accessing
    // `odoo.loader.modules`.  The promise is created here but resolved
    // explicitly at the END of the concatenated bundle via
    // `odoo.__legacyReady_resolve()` — guaranteeing that all define()
    // calls have been processed.
    //
    // If no bridge shims exist, this is a harmless no-op.
    odoo.__legacyReady = new Promise((r) => {
        odoo.__legacyReady_resolve = r;
    });
})(/** @type {any} */ (globalThis.odoo ||= {}));
