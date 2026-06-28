// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dependency_graph - Iterative DFS cycle detection and wave-based dependency resolution */

/**
 * Dependency graph utilities.
 *
 * Two pure helpers with no OWL or DOM dependencies:
 *
 *   - ``findDependencyCycle(graph)``: iterative DFS that returns the first
 *     cycle path it finds, or null.  Used both by the service launcher
 *     (``env.js``) and the module loader to explain why a graph is stuck.
 *
 *   - ``createWaveResolver(options)``: O(N+E) ready-queue engine.  Tracks
 *     named entries with dependency lists, emits ``shift()``able names
 *     whose deps are all met, and accepts ``propagate(name)`` callbacks
 *     to unblock dependents as each entry finishes.  Used by the service
 *     launcher; the loader shim keeps an inlined copy because it runs
 *     before ESM can import this module.
 *
 * @see env.js for the service-launcher integration
 * @see module_loader.js for the parallel inlined implementation (must be
 *      kept in sync with ``createWaveResolver`` — both share the same
 *      dedup/ready-queue semantics).
 */

/**
 * Find a cycle in a dependency graph, if one exists.
 *
 * Uses iterative DFS with explicit stack to avoid call-stack overflow on
 * pathologically deep graphs.
 *
 * @param {Map<string, string[]>} graph
 *     Map from node name to its dependency names.
 *     Nodes not present as keys are treated as external (no outgoing edges).
 * @returns {string[] | null}
 *     The cycle path (e.g. ["a", "b", "c", "a"]) or null if acyclic.
 */
export function findDependencyCycle(graph) {
    const NOT_VISITED = 0;
    const IN_STACK = 1;
    const DONE = 2;

    /** @type {Map<string, number>} */
    const state = new Map();
    for (const name of graph.keys()) {
        state.set(name, NOT_VISITED);
    }

    /** @type {Map<string, string | null>} parent pointers for path reconstruction */
    const parent = new Map();

    for (const startNode of graph.keys()) {
        if (state.get(startNode) === DONE) {
            continue;
        }

        // Iterative DFS using an explicit stack.
        // Each frame is [node, depIndex] — depIndex tracks which dependency
        // to visit next, avoiding re-processing already-visited deps.
        /** @type {Array<[string, number]>} */
        const stack = [[startNode, 0]];
        state.set(startNode, IN_STACK);
        parent.set(startNode, null);

        while (stack.length) {
            // `stack.length` is non-zero here, so the top frame exists. Index
            // (typed as the element type) rather than `.at(-1)` (typed
            // `T | undefined`) so the access is statically known-defined.
            const frame = stack[stack.length - 1];
            const node = frame[0];
            const deps = graph.get(node) || [];

            if (frame[1] >= deps.length) {
                // All deps processed — mark done and backtrack
                state.set(node, DONE);
                stack.pop();
                continue;
            }

            const dep = deps[frame[1]++];

            // Skip nodes not in the graph (external dependencies)
            if (!graph.has(dep)) {
                continue;
            }

            const depState = state.get(dep);
            if (depState === IN_STACK) {
                // Found a cycle — reconstruct the path
                return _reconstructCycle(parent, node, dep);
            }
            if (depState === DONE) {
                continue;
            }

            // Visit unvisited dep
            state.set(dep, IN_STACK);
            parent.set(dep, node);
            stack.push([dep, 0]);
        }
    }

    return null;
}

/**
 * Reconstruct a cycle path from parent pointers.
 *
 * @param {Map<string, string | null>} parent
 * @param {string} from - Node whose dependency closes the cycle
 * @param {string} to - The dependency that was already in the stack
 * @returns {string[]} The cycle path, e.g. ["a", "b", "c", "a"]
 */
function _reconstructCycle(parent, from, to) {
    // Walk backwards from `from` to `to` via parent pointers.
    // The cycle is: to → ... → from → to
    const path = [from];
    let current = from;
    while (current !== to) {
        current = /** @type {string} */ (parent.get(current));
        path.push(current);
    }
    path.reverse(); // Now: [to, ..., from]
    path.push(to); // Close the cycle
    return path;
}

/**
 * @typedef {object} WaveResolver
 * @property {(name: string, deps: Iterable<string>) => void} track
 *   Register an entry; returns immediately if already tracked.
 * @property {(name: string) => void} propagate
 *   Notify waiters that ``name`` is loaded; unblocks any whose last
 *   dep just resolved.
 * @property {() => string | undefined} shift
 *   Remove and return the next ready-to-start entry, or undefined.
 * @property {() => boolean} hasReady
 *   Cheap check for whether ``shift()`` would return a value.
 * @property {(name: string) => void} untrack
 *   Remove an entry from the resolver without firing propagate().
 *   Called on successful start OR on failure — the two cases differ
 *   only in whether ``propagate()`` is also called.
 * @property {(name: string) => number | undefined} pendingOf
 *   Diagnostics: current unmet-dep count, or undefined if not tracked.
 * @property {() => IterableIterator<string>} trackedNames
 *   Diagnostics: iterate names that are currently blocked.
 */

/**
 * Create an O(N+E) wave resolver for name/deps entries.
 *
 * The resolver does NOT start anything itself — it just surfaces names
 * whose deps are all met.  Callers drive the wave:
 *
 *     const r = createWaveResolver({ isLoaded: (n) => knownMap.has(n) });
 *     for (const [name, deps] of entries) r.track(name, deps);
 *     while (r.hasReady()) {
 *         const name = r.shift();
 *         startOne(name);           // the caller's work
 *         r.propagate(name);        // unblocks dependents
 *     }
 *
 * ``isLoaded(dep)`` is invoked during ``track`` to decide whether a
 * dep should count against the pending counter.  Deps that come from
 * outside the resolver (already-loaded entries, native pre-registered
 * names) return true and don't inflate the counter.
 *
 * @param {{ isLoaded: (dep: string) => boolean }} options
 * @returns {WaveResolver}
 */
export function createWaveResolver({ isLoaded }) {
    /** Count of unmet deps per tracked entry. @type {Map<string, number>} */
    const pending = new Map();
    /** Reverse graph: dep name → entries waiting on it. @type {Map<string, Set<string>>} */
    const dependents = new Map();
    /** FIFO of entries whose deps are all met. @type {string[]} */
    const ready = [];

    return {
        track(name, deps) {
            if (pending.has(name)) {
                // Idempotent: a second track call for the same name is
                // a no-op.  The caller may legitimately re-track in
                // response to registry updates; we don't want to
                // double-count dependencies.
                return;
            }
            let unmet = 0;
            for (const dep of deps) {
                if (!isLoaded(dep)) {
                    let waiters = dependents.get(dep);
                    if (!waiters) {
                        waiters = new Set();
                        dependents.set(dep, waiters);
                    }
                    // Dedup waiters: ``track("b", ["a", "a"])`` must
                    // unblock on a single propagate("a"), not wait for
                    // two.  Otherwise the entry deadlocks forever.
                    if (!waiters.has(name)) {
                        waiters.add(name);
                        unmet++;
                    }
                }
            }
            pending.set(name, unmet);
            if (unmet === 0) {
                ready.push(name);
            }
        },
        propagate(name) {
            const waiters = dependents.get(name);
            if (!waiters) {
                return;
            }
            for (const w of waiters) {
                const remaining = pending.get(w);
                if (remaining !== undefined) {
                    const c = remaining - 1;
                    pending.set(w, c);
                    if (c === 0) {
                        ready.push(w);
                    }
                }
            }
            dependents.delete(name);
        },
        shift() {
            return ready.shift();
        },
        hasReady() {
            return ready.length > 0;
        },
        untrack(name) {
            pending.delete(name);
        },
        pendingOf(name) {
            return pending.get(name);
        },
        trackedNames() {
            return pending.keys();
        },
    };
}
