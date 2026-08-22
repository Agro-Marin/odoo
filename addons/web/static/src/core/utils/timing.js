// @ts-check
/** @odoo-module native */

import { onWillUnmount, useComponent } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * @template {(...args: any[]) => any} T
 * @param {T} callback
 * @param {() => Promise<void>} [synchronize]
 * @returns {(...args: Parameters<T>) => Promise<Awaited<ReturnType<T>>>}
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

export const INPUT_DEBOUNCE_DELAY = 250;

/**
 * @template {Function} T
 * @param {T} func
 * @param {number | "animationFrame" | (() => number)} delay
 * @param {boolean | {leading?: boolean, trailing?: boolean}} [options]
 * @returns {T & { cancel: (execNow?: boolean) => void }}
 */
export function debounce(func, delay, options) {
    /** @type {any} */
    let handle;
    const funcName = func.name ? `${func.name} (debounce)` : "debounce";
    const getDelay = typeof delay === "function" ? delay : () => delay;
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
                    }, getDelay());
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
                lastSelf = null;
            },
        },
    );
}

/**
 * @param {(deltaTime: number) => void} callback
 * @returns {() => void}
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
 * @template {Function} T
 * @param {T} func
 * @returns {T & { cancel: () => void }}
 */
export function throttleForAnimation(func) {
    /** @type {any} */
    let handle = null;
    /**
     * @type {{ args: any[], resolve: (value: any) => any, reject: (reason?: any) => any } | null}
     */
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
 * @template {Function} T
 * @param {T} callback
 * @param {number | "animationFrame" | (() => number)} delay
 * @param {{execBeforeUnmount?: boolean, immediate?: boolean, trailing?: boolean}} [options]
 * @returns {T & { cancel: (execNow?: boolean) => void }}
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
 * @template {Function} T
 * @param {T} func
 * @returns {T & { cancel: () => void }}
 */
export function useThrottleForAnimation(func) {
    const component = useComponent();
    const throttledForAnimation = throttleForAnimation(func.bind(component));
    onWillUnmount(() => throttledForAnimation.cancel());
    return throttledForAnimation;
}
