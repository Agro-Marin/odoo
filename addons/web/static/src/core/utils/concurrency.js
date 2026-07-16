// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/concurrency - Async primitives: Mutex, KeepLast, Race, Deferred, and delay */

/**
 * Returns a promise resolved after 'wait' milliseconds
 *
 * @param {number} [wait=0] the delay in ms
 * @returns {Promise<void>}
 */
export function delay(wait) {
    return new Promise(function (resolve) {
        setTimeout(resolve, wait);
    });
}

/**
 * Error a {@link KeepLast} (in ``rejectSuperseded`` mode) rejects a superseded
 * task's wrapper with, making supersession a first-class, observable signal
 * instead of a promise that hangs forever.
 *
 * It is a *control-flow* signal, not a real failure: the global error service
 * swallows it (no dialog, no console — see
 * ``@web/components/errors/error_handlers``'s ``supersededErrorHandler``), so
 * an awaiter can simply let it propagate out of a ``try/finally`` and rely on
 * the cleanup running, without inventing a bespoke sentinel.
 */
export class SupersededError extends Error {
    constructor(message = "This task was superseded by a newer one") {
        super(message);
        this.name = "SupersededError";
    }
}

/**
 * KeepLast is a concurrency primitive that manages a list of tasks, and only
 * keeps the last task active.
 *
 * By default, when a new task is added, any previously pending task is silently
 * discarded — its wrapper promise never settles (back-compatible behavior: most
 * consumers just want the stale task's continuation to never run). Pass
 * ``{ rejectSuperseded: true }`` to instead REJECT a superseded task's wrapper
 * with a {@link SupersededError} — immediately at supersession time, so
 * awaiters observe the supersession (their ``finally`` runs, their ``await``
 * throws) rather than hanging forever, even when the stale underlying promise
 * itself never settles (e.g. a hung network request). This
 * opt-in mode is used by the action service, whose ``doAction`` awaiters must
 * be able to release UI blocking / restore state when superseded.
 *
 * @template T
 */
export class KeepLast {
    /**
     * @param {Object} [options]
     * @param {boolean} [options.rejectSuperseded=false] reject a superseded
     *   task's wrapper with a {@link SupersededError} instead of leaving it
     *   pending forever.
     */
    constructor({ rejectSuperseded = false } = {}) {
        this._id = 0;
        this._rejectSuperseded = rejectSuperseded;
        /**
         * ``rejectSuperseded`` mode only: reject callback of the currently
         * pending wrapper, so {@link add} can reject it AT supersession time.
         * Waiting for the stale underlying promise to settle instead would
         * hang the superseded awaiters forever if that promise never settles.
         *
         * @type {((reason: unknown) => void) | null}
         */
        this._rejectPending = null;
    }
    /**
     * Monotonic generation of this KeepLast: incremented on every {@link add}.
     * Consumers that need to detect "a newer task entered the KeepLast since I
     * snapshotted" (e.g. the action manager's navigation-supersession guard
     * around awaits performed OUTSIDE the KeepLast) read this instead of
     * reaching into the private ``_id`` slot.
     *
     * @returns {number}
     */
    get generation() {
        return this._id;
    }
    /**
     * Register a new task. If a task was already pending it is superseded:
     * its wrapper promise will never resolve or reject — unless
     * ``rejectSuperseded`` was set, in which case it rejects immediately
     * with a {@link SupersededError} (even if the stale underlying promise
     * never settles).
     *
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    add(promise) {
        this._id++;
        const currentId = this._id;
        if (this._rejectPending) {
            this._rejectPending(new SupersededError());
            this._rejectPending = null;
        }
        return new Promise((resolve, reject) => {
            if (this._rejectSuperseded) {
                this._rejectPending = reject;
            }
            promise.then(
                (value) => {
                    if (this._id === currentId) {
                        this._rejectPending = null;
                        resolve(value);
                    }
                    // else: superseded — silently discarded (default mode) or
                    // already rejected at supersession time (rejectSuperseded).
                },
                (reason) => {
                    if (this._id === currentId) {
                        this._rejectPending = null;
                        reject(reason);
                    }
                    // else: superseded — silently discarded (default mode) or
                    // already rejected at supersession time (rejectSuperseded).
                },
            );
        });
    }
}

/**
 * A (Odoo) mutex is a primitive for serializing computations.  This is
 * useful to avoid a situation where two computations modify some shared
 * state and cause some corrupted state.
 *
 * Imagine that we have a function to fetch some data _load(), which returns
 * a promise which resolves to something useful. Now, we have some code
 * looking like this::
 *
 *      return this._load().then(function (result) {
 *          this.state = result;
 *      });
 *
 * If this code is run twice, but the second execution ends before the
 * first, then the final state will be the result of the first call to
 * _load.  However, if we have a mutex::
 *
 *      this.mutex = new Mutex();
 *
 * and if we wrap the calls to _load in a mutex::
 *
 *      return this.mutex.exec(function() {
 *          return this._load().then(function (result) {
 *              this.state = result;
 *          });
 *      });
 *
 * Then, it is guaranteed that the final state will be the result of the
 * second execution.
 *
 * A Mutex has to be a class, and not a function, because we have to keep
 * track of some internal state.
 */
export class Mutex {
    constructor() {
        /** @type {Promise<any>} */
        this._lock = Promise.resolve();
        /** @type {number} */
        this._queueSize = 0;
        /** @type {Promise<void> | undefined} */
        this._unlockedProm = undefined;
        /** @type {(() => void) | undefined} */
        this._unlock = undefined;
    }
    /**
     * Whether a computation is currently running or queued. Lets callers
     * skip an ``await`` (and its microtask delay) when the mutex is
     * already free.
     */
    get locked() {
        return this._queueSize > 0;
    }

    /**
     * Add a computation to the queue, it will be executed as soon as the
     * previous computations are completed.
     *
     * @template T
     * @param {() => (T | Promise<T>)} action a function which may return a Promise
     * @returns {Promise<T>}
     */
    async exec(action) {
        this._queueSize++;
        if (!this._unlockedProm) {
            const { promise, resolve } =
                /** @type {{ promise: Promise<void>; resolve: () => void }} */ (
                    Promise.withResolvers()
                );
            this._unlockedProm = promise;
            this._unlock = () => {
                resolve();
                this._unlockedProm = undefined;
            };
        }
        const always = () => {
            let result;
            try {
                result = action();
            } catch (e) {
                result = Promise.reject(e);
            }
            return Promise.resolve(result).finally(() => {
                if (--this._queueSize === 0) {
                    // Always set by the time the queue drains (see exec above).
                    /** @type {() => void} */ (this._unlock)();
                }
            });
        };
        this._lock = this._lock.then(always, always);
        return this._lock;
    }
    /**
     * @returns {Promise<void>} resolved as soon as the Mutex is unlocked
     *   (directly if it is currently idle)
     */
    getUnlockedDef() {
        return this._unlockedProm || Promise.resolve();
    }
}

/**
 * Like Promise.race(), but dynamic: promises can be added to a Race at any
 * time, and each add() returns a promise that resolves as soon as any promise
 * in the race settles. Once settled, the next add() starts a new race.
 *
 * @template T
 */
export class Race {
    constructor() {
        /** @type {Promise<T> | null} */
        this.currentProm = null;
        /** @type {((value: T) => void) | null} */
        this.currentPromResolver = null;
        /** @type {((error: any) => void) | null} */
        this.currentPromRejecter = null;
        /** @type {number} Generation counter to protect against stale callbacks */
        this._generation = 0;
    }
    /**
     * Register a new promise. If there is an ongoing race, the promise is added
     * to that race. Otherwise, it starts a new race. The returned promise
     * resolves as soon as the race is over, with the value of the first resolved
     * promise added to the race.
     *
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    add(promise) {
        if (!this.currentProm) {
            this._generation++;
            const gen = this._generation;
            const { promise: raceProm, resolve, reject } = Promise.withResolvers();
            this.currentProm = raceProm;
            this.currentPromResolver = (value) => {
                if (this._generation !== gen) {
                    return; // stale callback from a previous race — ignore
                }
                this.currentProm = null;
                this.currentPromResolver = null;
                this.currentPromRejecter = null;
                resolve(value);
            };
            this.currentPromRejecter = (error) => {
                if (this._generation !== gen) {
                    return; // stale callback from a previous race — ignore
                }
                this.currentProm = null;
                this.currentPromResolver = null;
                this.currentPromRejecter = null;
                reject(error);
            };
        }
        promise.then(this.currentPromResolver, this.currentPromRejecter);
        return this.currentProm;
    }
    /**
     * @returns {Promise<T>|null} promise resolved as soon as the race is over, or
     *   null if there is no race ongoing)
     */
    getCurrentProm() {
        return this.currentProm;
    }
}

/**
 * A native Promise enriched with public `resolve` and `reject` methods.
 * The constructor returns a Promise (not a Deferred instance) due to the
 * constructor return override — prefer `Promise.withResolvers()` in new code.
 *
 * @template [T=unknown]
 * @returns {Promise<T> & { resolve: (value: T | PromiseLike<T>) => void, reject: (reason?: any) => void }}
 */
export class Deferred {
    constructor() {
        const { promise, resolve, reject } = Promise.withResolvers();
        return Object.assign(promise, { resolve, reject });
    }
}
