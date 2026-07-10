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
 * KeepLast is a concurrency primitive that manages a list of tasks, and only
 * keeps the last task active.  When a new task is added, any previously pending
 * task is silently discarded — its wrapper promise never settles.
 *
 * @template T
 */
export class KeepLast {
    constructor() {
        this._id = 0;
    }
    /**
     * Register a new task.  If a task was already pending it is superseded:
     * its wrapper promise will never resolve or reject.
     *
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    add(promise) {
        this._id++;
        const currentId = this._id;
        return new Promise((resolve, reject) => {
            promise.then(
                (value) => {
                    if (this._id === currentId) {
                        resolve(value);
                    }
                    // Superseded — silently discard.
                },
                (reason) => {
                    if (this._id === currentId) {
                        reject(reason);
                    }
                    // Superseded — silently discard.
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
