// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/timing - Batched callbacks, debounce, throttle, and recurring animation frame scheduling */

import { onWillUnmount, useComponent } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * Creates a batched version of a callback so that all calls to it in the same
 * time frame will only call the original callback once, with the LAST
 * arguments received.
 *
 * Every caller in a batch gets a promise settling with the callback's outcome,
 * not just the one that happened to open the batch. The naive shape (an
 * ``async`` wrapper whose body is skipped when a batch is already scheduled)
 * hands the later callers an already-resolved promise, so ``await batched(fn)()``
 * returns BEFORE ``fn`` has run — invisible under the default microtask
 * granularity, plainly wrong under an animation-frame one (``useRecordObserver``).
 * The callback's own async completion is awaited too, so the promise means
 * "the batch has run", which is what its type says.
 *
 * @template {(...args: any[]) => any} T
 * @param {T} callback the callback to batch
 * @param {() => Promise<void>} [synchronize] this function decides the granularity of the batch (a microtick by default)
 * @returns {(...args: Parameters<T>) => Promise<Awaited<ReturnType<T>>>} a batched version of the original callback
 */
export function batched(callback, synchronize = () => Promise.resolve()) {
    let scheduled = false;
    /** @type {any[]} */
    let lastArgs;
    /** @type {{ resolve: (value: any) => void, reject: (reason?: any) => void }[]} */
    let awaiters = [];
    return (/** @type {any[]} */ ...args) => {
        lastArgs = args;
        const { promise, resolve, reject } = Promise.withResolvers();
        awaiters.push({ resolve, reject });
        if (!scheduled) {
            scheduled = true;
            (async () => {
                await synchronize();
                scheduled = false;
                const settlers = awaiters;
                awaiters = [];
                try {
                    const result = await callback(...lastArgs);
                    for (const settler of settlers) {
                        settler.resolve(result);
                    }
                } catch (error) {
                    console.error(error);
                    for (const settler of settlers) {
                        settler.reject(error);
                    }
                }
            })();
        }
        return /** @type {any} */ (promise);
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
    /** @type {{ resolve: Function, reject: Function }[]} */
    let pending = [];

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
                        execute(this, args, [{ resolve, reject }]);
                    } else {
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
                if (execNow && trailing && lastArgs) {
                    const awaiters = pending;
                    pending = [];
                    execute(lastSelf, lastArgs, awaiters);
                } else if (pending.length) {
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
    let stopped = false;
    const handler = (/** @type {number} */ timestamp) => {
        callback(timestamp - lastTimestamp);
        lastTimestamp = timestamp;
        if (!stopped) {
            handle = browser.requestAnimationFrame(handler);
        }
    };

    const stop = () => {
        stopped = true;
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
    /** @type {{ args: any[], resolve: (value: any) => any, reject: (reason?: any) => any } | null} */
    let lastCall = null;
    const funcName = func.name
        ? `${func.name} (throttleForAnimation)`
        : "throttleForAnimation";
    /** @type {any} */
    let self;
    const pending = () => {
        if (lastCall) {
            handle = browser.requestAnimationFrame(pending);
            const { args, resolve, reject } = lastCall;
            lastCall = null;
            try {
                Promise.resolve(func.apply(self, args)).then(resolve, reject);
            } catch (error) {
                reject(error);
            }
        } else {
            handle = null;
        }
    };
    return Object.assign(
        {
            /** @type {any} */
            [funcName](/** @type {any[]} */ ...args) {
                self = this;
                return new Promise((resolve, reject) => {
                    const isNew = handle === null;
                    if (isNew) {
                        handle = browser.requestAnimationFrame(pending);
                        try {
                            Promise.resolve(func.apply(this, args)).then(
                                resolve,
                                reject,
                            );
                        } catch (error) {
                            reject(error);
                        }
                    } else {
                        if (lastCall) {
                            lastCall.resolve(undefined);
                        }
                        lastCall = { args, resolve, reject };
                    }
                });
            },
        }[funcName],
        {
            cancel() {
                browser.cancelAnimationFrame(handle);
                if (lastCall) {
                    lastCall.resolve(undefined);
                    lastCall = null;
                }
                handle = null;
            },
        },
    );
}

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
