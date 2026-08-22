// @ts-check
/** @odoo-module native */

/**
 * @param {Map<string, string[]>} graph
 * @returns {string[] | null}
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

    /** @type {Map<string, string | null>} */
    const parent = new Map();

    for (const startNode of graph.keys()) {
        if (state.get(startNode) === DONE) {
            continue;
        }

        /** @type {Array<[string, number]>} */
        const stack = [[startNode, 0]];
        state.set(startNode, IN_STACK);
        parent.set(startNode, null);

        while (stack.length) {
            const frame = stack[stack.length - 1];
            const node = frame[0];
            const deps = graph.get(node) || [];

            if (frame[1] >= deps.length) {
                state.set(node, DONE);
                stack.pop();
                continue;
            }

            const dep = deps[frame[1]++];

            if (!graph.has(dep)) {
                continue;
            }

            const depState = state.get(dep);
            if (depState === IN_STACK) {
                return _reconstructCycle(parent, node, dep);
            }
            if (depState === DONE) {
                continue;
            }

            state.set(dep, IN_STACK);
            parent.set(dep, node);
            stack.push([dep, 0]);
        }
    }

    return null;
}

/**
 * @param {Map<string, string | null>} parent
 * @param {string} from
 * @param {string} to
 * @returns {string[]}
 */
function _reconstructCycle(parent, from, to) {
    const path = [from];
    let current = from;
    while (current !== to) {
        current = /** @type {string} */ (parent.get(current));
        path.push(current);
    }
    path.reverse();
    path.push(to);
    return path;
}

/**
 * @typedef {object} WaveResolver
 * @property {(name: string, deps: Iterable<string>) => void} track
 * @property {(name: string) => void} propagate
 * @property {() => string | undefined} shift
 * @property {() => boolean} hasReady
 * @property {(name: string) => void} untrack
 * @property {(name: string) => number | undefined} pendingOf
 * @property {() => IterableIterator<string>} trackedNames
 */

/**
 * @param {{ isLoaded: (dep: string) => boolean }} options
 * @returns {WaveResolver}
 */
export function createWaveResolver({ isLoaded }) {
    /** @type {Map<string, number>} */
    const pending = new Map();
    /** @type {Map<string, Set<string>>} */
    const dependents = new Map();
    /**
     * @type {Map<string, string[]>}
     */
    const waitingOn = new Map();
    /** @type {string[]} */
    const ready = [];

    return {
        track(name, deps) {
            if (pending.has(name)) {
                return;
            }
            let unmet = 0;
            /** @type {string[]} */
            const owned = [];
            for (const dep of deps) {
                if (!isLoaded(dep)) {
                    let waiters = dependents.get(dep);
                    if (!waiters) {
                        waiters = new Set();
                        dependents.set(dep, waiters);
                    }
                    if (!waiters.has(name)) {
                        waiters.add(name);
                        owned.push(dep);
                        unmet++;
                    }
                }
            }
            waitingOn.set(name, owned);
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
            const readyIndex = ready.indexOf(name);
            if (readyIndex !== -1) {
                ready.splice(readyIndex, 1);
            }
            const owned = waitingOn.get(name);
            if (owned) {
                for (const dep of owned) {
                    const waiters = dependents.get(dep);
                    if (waiters) {
                        waiters.delete(name);
                        if (waiters.size === 0) {
                            dependents.delete(dep);
                        }
                    }
                }
                waitingOn.delete(name);
            }
        },
        pendingOf(name) {
            return pending.get(name);
        },
        trackedNames() {
            return pending.keys();
        },
    };
}
