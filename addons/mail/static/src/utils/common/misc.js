// @ts-check
/** @odoo-module native */
import { observeKey } from "@mail/model/store";
import { AssetsLoadingError, getBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { Deferred } from "@web/core/utils/concurrency";
import { memoize } from "@web/core/utils/functions";
import { effect } from "@web/core/utils/reactive";

const log = makeLogger("mail.utils");
/**
 * @template {Object} T
 * @param {T} obj
 * @param {Object<string, any>} data
 * @param {string[]} [keys=Object.keys(data)]
 * @returns {T}
 */
export function assignDefined(obj, data, keys = Object.keys(data)) {
    const target = /** @type {Object<string, any>} */ (obj);
    for (const key of keys) {
        if (data[key] !== undefined) {
            target[key] = data[key];
        }
    }
    return obj;
}

/**
 * @param {Object} obj
 * @param {Object<string, () => any>} data
 */
export function assignGetter(obj, data) {
    const properties = Object.fromEntries(
        Object.entries(data).map(([getterName, getterFn]) => [
            getterName,
            {
                get: getterFn,
                set: () => {},
            },
        ]),
    );
    Object.defineProperties(obj, properties);
}

/**
 * @template {Object} T
 * @param {T} obj
 * @param {Object<string, any>} data
 * @param {string[]} [keys=Object.keys(data)]
 * @returns {T}
 */
export function assignIn(obj, data, keys = Object.keys(data)) {
    const target = /** @type {Object<string, any>} */ (obj);
    for (const key of keys) {
        if (key in data) {
            target[key] = data[key];
        }
    }
    return obj;
}

/**
 * @template T
 * @param {T[]} list
 * @param {number} target
 * @param {(item: T) => number} [itemToCompareVal]
 * @returns {T|null}
 */
export function nearestGreaterThanOrEqual(list, target, itemToCompareVal) {
    /**
     * @param {number} left
     * @param {number} right
     * @param {T|null} next
     * @returns {T|null}
     */
    const findNext = (left, right, next) => {
        if (left > right) {
            return next;
        }
        const index = Math.floor((left + right) / 2);
        const item = list[index];
        const val = /** @type {number} */ (itemToCompareVal?.(item) ?? item);
        if (val === target) {
            return item;
        } else if (val > target) {
            return findNext(left, index - 1, item);
        } else {
            return findNext(index + 1, right, next);
        }
    };
    return findNext(0, list.length - 1, null);
}

/**
 * @param {DataTransfer} dataTransfer
 * @returns {boolean}
 */
export function isDragSourceExternalFile(dataTransfer) {
    const dragDataType = dataTransfer.types;
    if (dragDataType.constructor === window.DOMStringList) {
        return /** @type {DOMStringList} */ (
            /** @type {unknown} */ (dragDataType)
        ).contains("Files");
    }
    if (dragDataType.constructor === Array) {
        return /** @type {string[]} */ (dragDataType).includes("Files");
    }
    return false;
}

/**
 * @param {Object} target
 * @param {string|string[]} key
 * @param {Function} callback
 * @returns {() => void}
 */
export function onChange(target, key, callback) {
    return observeKey(target, key, (observe) => {
        observe();
        callback();
    });
}

/** @param {MediaStream} [stream] */
export function closeStream(stream) {
    stream?.getTracks?.().forEach((track) => track.stop());
}

/**
 * @param {import("@web/core/l10n/dates").NullableDateTime} date1
 * @param {import("@web/core/l10n/dates").NullableDateTime} date2
 * @returns {number}
 */
export function compareDatetime(date1, date2) {
    if ((date1 || undefined)?.ts === (date2 || undefined)?.ts) {
        return 0;
    }
    if (!date1) {
        return -1;
    }
    if (!date2) {
        return 1;
    }
    return date1.ts - date2.ts;
}

/**
 * @param {string} v1
 * @param {string} v2
 * @returns {number}
 */
function compareVersion(v1, v2) {
    const parts1 = v1.split(".");
    const parts2 = v2.split(".");

    for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
        const num1 = parseInt(parts1[i]) || 0;
        const num2 = parseInt(parts2[i]) || 0;
        if (num1 < num2) {
            return -1;
        }
        if (num1 > num2) {
            return 1;
        }
    }
    return 0;
}

/**
 * @param {string} v
 * @returns {{isLowerThan: (other: string) => boolean}}
 */
export function parseVersion(v) {
    return {
        /**
         * @param {string} other
         * @returns {boolean}
         */
        isLowerThan(other) {
            return compareVersion(v, other) < 0;
        },
    };
}

/**
 * @param {string} url
 * @returns {{url: string|null, provider: "youtube"|"google-drive"|null}}
 */
export function convertToEmbedURL(url) {
    let parsed;
    try {
        parsed = new URL(url);
    } catch {
        return { url: null, provider: null };
    }
    const host = parsed.hostname.replace(/^(www|m|music)\./, "");
    if (["youtube.com", "youtube-nocookie.com", "youtu.be"].includes(host)) {
        let videoId;
        if (host === "youtu.be") {
            videoId = parsed.pathname.split("/")[1];
        } else if (parsed.searchParams.get("v")) {
            videoId = parsed.searchParams.get("v");
        } else {
            videoId = parsed.pathname.match(
                /^\/(?:embed|live|v|shorts)\/([^/?#&]+)/,
            )?.[1];
        }
        if (videoId) {
            const youtubeURL = new URL(`/embed/${videoId}`, "https://www.youtube.com");
            youtubeURL.searchParams.set("autoplay", "1");
            return { url: youtubeURL.toString(), provider: "youtube" };
        }
    }
    if (host === "drive.google.com") {
        const gdriveMatch = url.match(/(?:file\/d\/|open\?id=|uc\?id=)([^/?&]+)/);
        if (gdriveMatch) {
            const gdriveURL = new URL(
                `/file/d/${gdriveMatch[1]}/preview`,
                "https://drive.google.com",
            );
            return { url: gdriveURL.toString(), provider: "google-drive" };
        }
    }
    return { url: null, provider: null };
}

/** @returns {boolean} */
export const hasHardwareAcceleration = memoize(() => {
    const canvas = document.createElement("canvas");
    const gl = /** @type {WebGLRenderingContext|null} */ (
        canvas.getContext("webgl2") ||
            canvas.getContext("webgl") ||
            canvas.getContext("experimental-webgl")
    );
    if (!gl) {
        return false;
    }
    const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
    if (debugInfo) {
        const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
        if (/swiftshader|llvmpipe|software/i.test(renderer)) {
            return false;
        }
    }
    return true;
});

/**
 * @template {object} T
 * @param {Object} options
 * @param {(...dependencies: any[]) => void | (() => void)} options.effect
 * @param {(...args: T[]) => Object<string, any>|any[]} options.dependencies
 * @param {T[]} options.reactiveTargets
 */
export function effectWithCleanup({ effect: effectFn, dependencies, reactiveTargets }) {
    /** @type {(() => void)|void} */
    let cleanup;
    /** @type {Object<string, any>|any[]|undefined} */
    let prevDependencies;
    effect(
        /** @param {...any} deps */ (...deps) => {
            const nextDependencies = dependencies(...deps);
            const changed =
                !prevDependencies ||
                (Array.isArray(nextDependencies)
                    ? nextDependencies.some((v, i) => v !== prevDependencies[i])
                    : Object.keys(nextDependencies).some(
                          (key) =>
                              nextDependencies[key] !==
                              /** @type {Object<string, any>} */ (prevDependencies)[
                                  key
                              ],
                      ));
            if (changed) {
                prevDependencies = Array.isArray(nextDependencies)
                    ? [...nextDependencies]
                    : { ...nextDependencies };
                if (cleanup) {
                    cleanup();
                }
                cleanup = Array.isArray(nextDependencies)
                    ? effectFn(...nextDependencies)
                    : effectFn({ ...nextDependencies });
            }
        },
        reactiveTargets,
    );
}

/**
 * @template {object} T
 * @template {Object<string, any>} D
 * @param {Object} options
 * @param {(dependencies: D) => (() => void)} options.effect
 * @param {number} options.delay
 * @param {(...targets: T[]) => D} options.dependencies
 * @param {(...targets: T[]) => boolean} options.predicate
 * @param {T[]} options.reactiveTargets
 */
export function effectWithDebouncedCleanup({
    delay,
    dependencies,
    effect: effectFn,
    predicate,
    reactiveTargets,
}) {
    /** @type {ReturnType<typeof setTimeout>} */
    let timeout;
    let active = false;
    /** @type {() => void} */
    let cleanup;
    effectWithCleanup({
        /** @param {D & { predicate: boolean }} ctx */
        effect(ctx) {
            const { predicate, ...deps } = ctx;
            if (!predicate) {
                return;
            }
            clearTimeout(timeout);
            if (!active) {
                cleanup = effectFn(/** @type {D} */ (/** @type {unknown} */ (deps)));
                active = true;
            }
            return () => {
                timeout = setTimeout(() => {
                    cleanup();
                    active = false;
                }, delay);
            };
        },
        dependencies: /** @param {...T} targets */ (...targets) => ({
            predicate: predicate(...targets),
            ...dependencies(...targets),
        }),
        reactiveTargets,
    });
}

/**
 * @param {HTMLElement | ShadowRoot} targetNode
 * @param {string} bundleName
 */
export async function loadCssFromBundle(targetNode, bundleName) {
    const endLoad = log.perf("loadCssFromBundle");
    try {
        const res = await getBundle(bundleName);
        for (const url of res.cssLibs) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = url;
            targetNode.appendChild(link);
            await new Promise((res, rej) => {
                link.addEventListener("load", res);
                link.addEventListener("error", rej);
            });
        }
        endLoad({ bundleName, cssLibs: res.cssLibs.length });
    } catch (e) {
        endLoad({ bundleName, failed: true });
        if (e instanceof AssetsLoadingError && e.cause instanceof TypeError) {
            log.logic("loadCssFromBundle stalls on a network TypeError", () => ({
                bundleName,
            }));
            return new Promise(() => {});
        } else {
            throw e;
        }
    }
}

/**
 * @returns {<T>(func: () => Promise<T>) => Promise<T | undefined>}
 */
export function makeSequential() {
    let inProgress = false;
    /** @type {(() => Promise<any>)|undefined} */
    let nextFunction;
    /** @type {((value?: any) => void)|undefined} */
    let nextResolve;
    /** @type {((reason?: any) => void)|undefined} */
    let nextReject;
    async function call() {
        const resolve = nextResolve;
        const reject = nextReject;
        const func = nextFunction;
        nextResolve = undefined;
        nextReject = undefined;
        nextFunction = undefined;
        inProgress = true;
        try {
            const data = await func();
            resolve(data);
        } catch (e) {
            reject(e);
        }
        inProgress = false;
        if (nextFunction && nextResolve) {
            call();
        }
    }
    return (/** @type {() => Promise<any>} */ func) => {
        nextResolve?.();
        const prom = new Promise((resolve, reject) => {
            nextResolve = resolve;
            nextReject = reject;
        });
        nextFunction = func;
        if (!inProgress) {
            call();
        }
        return prom;
    };
}

export const SCROLL_END_TIMEOUT = 3000;
export const SCROLL_END_FALLBACK_DELAY = 250;

/**
 * Settles once a smooth scroll ends: on the target's `scrollend` where the browser
 * fires it (with a timeout in case it never does), after a fixed delay elsewhere.
 * `settle()` ends the wait early and releases the listener and the timer.
 *
 * @param {Object} [options]
 * @param {EventTarget} [options.target] only a `scrollend` from this element counts
 * @param {() => void} [options.onSettle] runs synchronously when the wait ends, once
 * @returns {Deferred<void> & { settle: () => void }}
 */
export function awaitScrollEnd({ target, onSettle } = {}) {
    const deferred = /** @type {Deferred<void> & { settle: () => void }} */ (
        new Deferred()
    );
    /** @type {ReturnType<typeof browser.setTimeout>} */
    let timeout;
    let settled = false;
    const settle = () => {
        if (settled) {
            return;
        }
        settled = true;
        browser.clearTimeout(timeout);
        document.removeEventListener("scrollend", onScrollEnd, { capture: true });
        onSettle?.();
        deferred.resolve();
    };
    /** @param {Event} ev */
    const onScrollEnd = (ev) => {
        if (!target || ev.target === target) {
            settle();
        }
    };
    if ("onscrollend" in window) {
        document.addEventListener("scrollend", onScrollEnd, { capture: true });
        timeout = browser.setTimeout(settle, SCROLL_END_TIMEOUT);
    } else {
        timeout = browser.setTimeout(settle, SCROLL_END_FALLBACK_DELAY);
    }
    deferred.settle = settle;
    return deferred;
}

/**
 * @param {"first"|"last"|"previous"|"next"} direction
 * @param {number|null} activeIndex
 * @param {number} length
 * @returns {number|undefined} the index to activate, wrapping at both ends
 */
export function navigateIndex(direction, activeIndex, length) {
    if (length === 0) {
        return undefined;
    }
    const current = activeIndex ?? 0;
    switch (direction) {
        case "first":
            return 0;
        case "last":
            return length - 1;
        case "previous":
            return current - 1 < 0 ? length - 1 : current - 1;
        case "next":
            return current + 1 > length - 1 ? 0 : current + 1;
        default:
            return undefined;
    }
}
