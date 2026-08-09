// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/concurrency */

import { browser } from "@web/core/browser/browser";

/**
 * @param {number} [wait=0]
 * @returns {Promise<void>}
 */
export function delay(wait) {
    return new Promise(function (resolve) {
        browser.setTimeout(resolve, wait);
    });
}

export class SupersededError extends Error {
    constructor(message = "This task was superseded by a newer one") {
        super(message);
        this.name = "SupersededError";
    }
}

/**
 * @template T
 */
export class KeepLast {
    /**
     * @param {Object} [options]
     * @param {boolean} [options.rejectSuperseded=false]
     */
    constructor({ rejectSuperseded = false } = {}) {
        this._id = 0;
        this._rejectSuperseded = rejectSuperseded;
        /**
         * @type {((reason: unknown) => void) | null}
         */
        this._rejectPending = null;
        /**
         * Disposer for the entry currently in flight, run by `cancel()`.
         *
         * Suppressing a superseded result and cancelling the work that produces
         * it are two different things, and this class only ever did the first:
         * a superseded `web_search_read` ran to completion on the server and had
         * its payload dropped on arrival. `add()` now registers whatever the
         * caller (or the promise itself) offers as a way to stop that work, and
         * `cancel()` runs it.
         *
         * @type {(() => void) | null}
         */
        this._abortPending = null;
    }
    /**
     * @returns {number}
     */
    get generation() {
        return this._id;
    }
    /**
     * Drops whatever is in flight without enqueuing a replacement: the pending
     * promise stops being the last one, so it can never settle its caller.
     */
    cancel() {
        this._id++;
        const abort = this._abortPending;
        this._abortPending = null;
        if (abort) {
            // A disposer that throws must not leave this instance wedged --
            // the supersede has to complete either way.
            try {
                abort();
            } catch (error) {
                console.warn("[KeepLast] abort handler threw", error);
            }
        }
        if (this._rejectPending) {
            this._rejectPending(new SupersededError());
            this._rejectPending = null;
        }
    }
    /**
     * @param {Promise<T>} promise
     * @param {Object} [options]
     * @param {() => void} [options.abort] cancels the work behind `promise`
     *   when a newer entry supersedes it. Defaults to `promise.abort(true)`
     *   when the promise carries one, which is the shape `rpc()` returns --
     *   so `keepLast.add(orm.call(...))` cancels its request with no wiring.
     *   Pass explicitly for composite promises (an `async` function issuing
     *   several RPCs has no `abort` of its own): hand in the `abort` of an
     *   `AbortController` whose signal reached those calls.
     * @returns {Promise<T>}
     */
    add(promise, { abort } = {}) {
        this.cancel();
        const currentId = this._id;
        const ownAbort =
            abort ??
            (typeof (/** @type {any} */ (promise)?.abort) === "function"
                ? // Reject rather than abort silently. `abort(false)` leaves the
                  // underlying promise pending forever, which does not remove
                  // the dangling continuation -- it only moves it from the
                  // caller into the async frames below. Rejecting unwinds them.
                  // Nothing leaks as an unhandled rejection: the handlers this
                  // method attaches below consume it and, seeing a stale
                  // generation, do nothing with it.
                  () => /** @type {any} */ (promise).abort(true)
                : null);
        this._abortPending = ownAbort;
        return new Promise((resolve, reject) => {
            if (this._rejectSuperseded) {
                this._rejectPending = reject;
            }
            promise.then(
                (value) => {
                    if (this._id === currentId) {
                        this._rejectPending = null;
                        // Settled as the winner: there is nothing left to
                        // abort, and a later `cancel()` must not reach back
                        // into finished work.
                        this._abortPending = null;
                        resolve(value);
                    }
                },
                (reason) => {
                    if (this._id === currentId) {
                        this._rejectPending = null;
                        this._abortPending = null;
                        reject(reason);
                    }
                },
            );
        });
    }
}

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
    get locked() {
        return this._queueSize > 0;
    }

    /**
     * @template T
     * @param {() => (T | Promise<T>)} action
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
                    /** @type {() => void} */ (this._unlock)();
                }
            });
        };
        this._lock = this._lock.then(always, always);
        return this._lock;
    }
    /**
     * @returns {Promise<void>}
     */
    getUnlockedDef() {
        return this._unlockedProm || Promise.resolve();
    }
}

/**
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
        /** @type {number} */
        this._generation = 0;
    }
    /**
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
                    return;
                }
                this.currentProm = null;
                this.currentPromResolver = null;
                this.currentPromRejecter = null;
                resolve(value);
            };
            this.currentPromRejecter = (error) => {
                if (this._generation !== gen) {
                    return;
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
     * @returns {Promise<T>|null}
     */
    getCurrentProm() {
        return this.currentProm;
    }
}

export class InFlight {
    constructor() {
        this._count = 0;
        /** @type {Promise<void> & { resolve: () => void } | null} */
        this._idle = null;
    }
    /** @returns {boolean} */
    get isBusy() {
        return this._count > 0;
    }
    /**
     * @template T
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    track(promise) {
        this._count++;
        this._idle ||= /** @type {any} */ (new Deferred());
        const settled = () => {
            if (--this._count === 0) {
                const idle = /** @type {any} */ (this._idle);
                this._idle = null;
                idle.resolve();
            }
        };
        promise.then(settled, settled);
        return promise;
    }
    /**
     * @returns {Promise<void>}
     */
    whenIdle() {
        return this._idle || Promise.resolve();
    }
}

/**
 * @template [T=unknown]
 * @returns {Promise<T> & { resolve: (value: T | PromiseLike<T>) => void, reject: (reason?: any) => void }}
 */
export class Deferred {
    constructor() {
        const { promise, resolve, reject } = Promise.withResolvers();
        return Object.assign(promise, { resolve, reject });
    }
}
