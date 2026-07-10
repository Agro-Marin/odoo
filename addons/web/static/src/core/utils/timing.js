// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/timing - Batched callbacks, debounce, throttle, and recurring animation frame scheduling */

import { onWillUnmount, useComponent } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * Creates a batched version of a callback so that all calls to it in the same
 * time frame will only call the original callback once.
 * @param {Function} callback the callback to batch
 * @param {() => Promise<void>} [synchronize] this function decides the granularity of the batch (a microtick by default)
 * @returns {(...args: any[]) => Promise<void>} a batched version of the original callback
 */
export function batched(callback, synchronize = () => Promise.resolve()) {
    let scheduled = false;
    let lastArgs;
    return async (...args) => {
        lastArgs = args;
        if (!scheduled) {
            scheduled = true;
            await synchronize();
            scheduled = false;
            callback(...lastArgs);
        }
    };
}

/**
 * Creates and returns a new debounced version of the passed function (func)
 * which will postpone its execution until after 'delay' milliseconds
 * have elapsed since the last time it was invoked. The debounced function
 * will return a Promise that will be resolved when the function (func)
 * has been fully executed.
 *
 * If both `options.trailing` and `options.leading` are true, the function
 * will only be invoked at the trailing edge if the debounced function was
 * called at least once more during the wait time.
 *
 * @template {Function} T the return type of the original function
 * @param {T} func the function to debounce
 * @param {number | "animationFrame"} delay how long should elapse before the function
 *      is called. If 'animationFrame' is given instead of a number, 'requestAnimationFrame'
 *      will be used instead of 'setTimeout'.
 * @param {boolean | {leading?: boolean, trailing?: boolean}} [options] if boolean: true=leading-only, false=trailing-only. If object: configure leading/trailing independently.
 * @returns {T & { cancel: () => void }} the debounced function
 */
export function debounce(func, delay, options) {
    /** @type {any} */
    let handle;
    const funcName = func.name ? `${func.name} (debounce)` : "debounce";
    const useAnimationFrame = delay === "animationFrame";
    const setFnName = useAnimationFrame ? "requestAnimationFrame" : "setTimeout";
    const clearFnName = useAnimationFrame ? "cancelAnimationFrame" : "clearTimeout";
    /** @type {any[] | null} */
    let lastArgs;
    let leading = false;
    let trailing = true;
    if (typeof options === "boolean") {
        leading = options;
        trailing = !options;
    } else if (options) {
        leading = options.leading ?? leading;
        trailing = options.trailing ?? trailing;
    }

    /** @type {any} */
    let lastSelf;
    // Deferreds of calls not run on the leading edge; the trailing execution
    // settles them all, so a thrown/rejected func propagates to every awaiter
    // (so `await debounced()` and `.catch()` work) instead of hanging forever.
    /** @type {{ resolve: Function, reject: Function }[]} */
    let pending = [];

    // Run `func`, then settle the given awaiters with its result (or error).
    /**
     * @param {any} self
     * @param {any[]} args
     * @param {{ resolve: Function, reject: Function }[]} awaiters
     */
    function execute(self, args, awaiters) {
        let result;
        try {
            result = func.apply(self, args);
        } catch (error) {
            for (const { reject } of awaiters) {
                reject(error);
            }
            return;
        }
        Promise.resolve(result).then(
            (value) => {
                for (const { resolve } of awaiters) {
                    resolve(value);
                }
            },
            (error) => {
                for (const { reject } of awaiters) {
                    reject(error);
                }
            },
        );
    }

    return Object.assign(
        {
            /** @type {any} */
            [funcName](/** @type {any[]} */ ...args) {
                lastSelf = this;
                return new Promise((resolve, reject) => {
                    if (leading && !handle) {
                        // Leading edge: run now and settle only this call.
                        execute(this, args, [{ resolve, reject }]);
                    } else {
                        // Defer to the trailing execution, queued with the others.
                        pending.push({ resolve, reject });
                        lastArgs = args;
                    }
                    browser[clearFnName](handle);
                    handle = /** @type {any} */ (browser)[setFnName](() => {
                        handle = null;
                        if (trailing && lastArgs) {
                            const awaiters = pending;
                            pending = [];
                            execute(lastSelf, lastArgs, awaiters);
                            lastArgs = null;
                        } else {
                            // Leading-only mode: calls queued while the timer was
                            // armed will never run. Settle them with `undefined`
                            // (same semantics as cancel()) and drop the stale args
                            // so cancel(true) can't replay them later.
                            const awaiters = pending;
                            pending = [];
                            lastArgs = null;
                            for (const { resolve } of awaiters) {
                                resolve(undefined);
                            }
                        }
                    }, delay);
                });
            },
        }[funcName],
        {
            cancel(execNow = false) {
                browser[clearFnName](handle);
                handle = null;
                if (execNow && lastArgs) {
                    const awaiters = pending;
                    pending = [];
                    execute(lastSelf, lastArgs, awaiters);
                } else if (pending.length) {
                    // Release awaiters that will now never run so a caller that
                    // `await`s the debounced fn (e.g. on willUnmount) doesn't hang.
                    const awaiters = pending;
                    pending = [];
                    for (const { resolve } of awaiters) {
                        resolve(undefined);
                    }
                }
                lastArgs = null;
            },
        },
    );
}

/**
 * Function that calls recursively a request to an animation frame.
 * Useful to call a function repetitively, until asked to stop, that needs constant rerendering.
 * The provided callback gets as argument the time the last frame took.
 * @param {(deltaTime: number) => void} callback
 * @returns {() => void} stop function
 */
export function setRecurringAnimationFrame(callback) {
    const handler = (/** @type {number} */ timestamp) => {
        callback(timestamp - lastTimestamp);
        lastTimestamp = timestamp;
        handle = browser.requestAnimationFrame(handler);
    };

    const stop = () => {
        browser.cancelAnimationFrame(handle);
    };

    let lastTimestamp = browser.performance.now();
    let handle = browser.requestAnimationFrame(handler);

    return stop;
}

/**
 * Creates a version of the function where only the last call between two
 * animation frames is executed before the browser's next repaint. This
 * effectively throttles the function to the display's refresh rate.
 * Note that the throttled function can be any callback. It is not
 * specifically an event handler, no assumption is made about its
 * signature.
 * NB: The first call is always called immediately (leading edge).
 *
 * @template {Function} T
 * @param {T} func the function to throttle
 * @returns {T & { cancel: () => void }} the throttled function
 */
export function throttleForAnimation(func) {
    /** @type {any} */
    let handle = null;
    // Only the last pending call matters — use a single variable instead of
    // a Set + spread-to-array which allocated on every animation frame tick.
    /** @type {{ args: any[], resolve: Function } | null} */
    let lastCall = null;
    const funcName = func.name
        ? `${func.name} (throttleForAnimation)`
        : "throttleForAnimation";
    /** @type {any} */
    let self;
    const pending = () => {
        if (lastCall) {
            handle = browser.requestAnimationFrame(pending);
            const { args, resolve } = lastCall;
            lastCall = null;
            Promise.resolve(func.apply(self, args)).then(
                /** @type {(v: any) => any} */ (resolve),
            );
        } else {
            handle = null;
        }
    };
    return Object.assign(
        {
            /** @type {any} */
            [funcName](/** @type {any[]} */ ...args) {
                self = this;
                return new Promise((resolve) => {
                    const isNew = handle === null;
                    if (isNew) {
                        handle = browser.requestAnimationFrame(pending);
                        Promise.resolve(func.apply(this, args)).then(resolve);
                    } else {
                        if (lastCall) {
                            // Settle the superseded call with `undefined` (same
                            // contract as cancel() and debounce's superseded
                            // awaiters) — else `await throttled(...)` hangs forever.
                            lastCall.resolve(undefined);
                        }
                        lastCall = { args, resolve };
                    }
                });
            },
        }[funcName],
        {
            cancel() {
                browser.cancelAnimationFrame(handle);
                if (lastCall) {
                    // Settle the dropped call with `undefined` (same contract as
                    // debounce().cancel()) so an awaiter doesn't hang forever.
                    lastCall.resolve(undefined);
                    lastCall = null;
                }
                handle = null;
            },
        },
    );
}

// ----------------------------------- HOOKS -----------------------------------

/**
 * Hook that returns a debounced version of the given function, and cancels
 * the potential pending execution on willUnmount.
 * @see debounce
 * @template {Function} T
 * @param {T} callback
 * @param {number | "animationFrame"} delay
 * @param {{execBeforeUnmount?: boolean, immediate?: boolean, trailing?: boolean}} [options]
 * @returns {T & { cancel: () => void }}
 */
export function useDebounced(
    callback,
    delay,
    { execBeforeUnmount = false, immediate = false, trailing = !immediate } = {},
) {
    const component = useComponent();
    const debounced = debounce(callback.bind(component), delay, {
        leading: immediate,
        trailing,
    });
    onWillUnmount(() => debounced.cancel(execBeforeUnmount));
    return debounced;
}

/**
 * Hook that returns a throttled for animation version of the given function,
 * and cancels the potential pending execution on willUnmount.
 * @see throttleForAnimation
 * @template {Function} T
 * @param {T} func the function to throttle
 * @returns {T & { cancel: () => void }} the throttled function
 */
export function useThrottleForAnimation(func) {
    const component = useComponent();
    const throttledForAnimation = throttleForAnimation(func.bind(component));
    onWillUnmount(() => throttledForAnimation.cancel());
    return throttledForAnimation;
}
