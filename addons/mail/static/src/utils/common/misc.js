/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { AssetsLoadingError, getBundle } from "@web/core/assets";
import { memoize } from "@web/core/utils/functions";
import { effect } from "@web/core/utils/reactive";
export function assignDefined(obj, data, keys = Object.keys(data)) {
    for (const key of keys) {
        if (data[key] !== undefined) {
            obj[key] = data[key];
        }
    }
    return obj;
}

export function assignGetter(obj, data) {
    const properties = Object.fromEntries(
        Object.entries(data).map(([getterName, getterFn]) => [
            getterName,
            {
                get: getterFn,
                set: () => {}, // avoids Proxy "trap returned falsish" error
            },
        ]),
    );
    Object.defineProperties(obj, properties);
}

export function assignIn(obj, data, keys = Object.keys(data)) {
    for (const key of keys) {
        if (key in data) {
            obj[key] = data[key];
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
    const findNext = (left, right, next) => {
        if (left > right) {
            return next;
        }
        const index = Math.floor((left + right) / 2);
        const item = list[index];
        const val = itemToCompareVal?.(item) ?? item;
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

export const mailGlobal = {
    isInTest: false,
};

// todo: move this some other place in the future
export function isDragSourceExternalFile(dataTransfer) {
    const dragDataType = dataTransfer.types;
    if (dragDataType.constructor === window.DOMStringList) {
        return dragDataType.contains("Files");
    }
    if (dragDataType.constructor === Array) {
        return dragDataType.includes("Files");
    }
    return false;
}

/**
 * Observe one or several keys of a reactive object.
 *
 * Mirrors the contract of `Store.onChange` (@see model/store.js `_onChange`),
 * including its disposal semantics: OWL has no unsubscribe API, so the
 * registered callback stays in `targetToKeysToCallbacks` — holding a STRONG
 * reference to everything it closes over — until the observed key next
 * changes, and forever if it never does. Callers with a bounded lifetime
 * (components above all) MUST call the returned disposer, which both latches
 * the callback off and drops its captures.
 *
 * @param {Object} target
 * @param {string|string[]} key
 * @param {Function} callback
 * @returns {() => void} disposer; idempotent
 */
export function onChange(target, key, callback) {
    if (Array.isArray(key)) {
        const disposers = key.map((k) => onChange(target, k, callback));
        return () => {
            for (const dispose of disposers) {
                dispose();
            }
        };
    }
    let proxy;
    function _observe() {
        // access proxy[key] only once to avoid triggering reactive get() many times
        const val = proxy?.[key];
        if (typeof val === "object" && val !== null) {
            void Object.keys(val);
        }
        if (Array.isArray(val)) {
            void val.length;
            void val.forEach((i) => i);
        }
    }
    let ready = true;
    proxy = reactive(target, () => {
        if (!ready) {
            return;
        }
        _observe();
        callback();
    });
    _observe();
    return () => {
        ready = false;
        proxy = undefined;
        target = undefined;
        callback = undefined;
    };
}

/**
 * @param {MediaStream} [stream]
 */
export function closeStream(stream) {
    stream?.getTracks?.().forEach((track) => track.stop());
}

/**
 * Compare two Luxon datetime.
 *
 * @param {import("@web/core/l10n/dates").NullableDateTime} date1
 * @param {import("@web/core/l10n/dates").NullableDateTime} date2
 * @returns {number} Negative if date1 is less than date2, positive if date1 is
 *  greater than date2, and 0 if they are equal.
 */
export function compareDatetime(date1, date2) {
    if (date1?.ts === date2?.ts) {
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
 * Compares two version strings.
 *
 * @param {string} v1 - The first version string to compare.
 * @param {string} v2 - The second version string to compare.
 * @returns {number} -1 if v1 is less than v2, 1 if v1 is greater than v2, and 0 if they are equal.
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
 * Return a version object that can be compared to other version strings.
 *
 * @param {string} v The version string to evaluate.
 */
export function parseVersion(v) {
    return {
        isLowerThan(other) {
            return compareVersion(v, other) < 0;
        },
    };
}

/**
 * Converts a YouTube or Google Drive URL into its embed format, extracting the
 * video ID or content identifier from the input URL.
 *
 * @param {string} url
 */
export function convertToEmbedURL(url) {
    // anchor on the hostname: matching any url whose path merely contains
    // /v/, /embed/, ?v=… renders an autoplaying YouTube embed for a
    // non-YouTube link (content spoofing in link previews)
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

/**
 * Checks if the browser supports hardware acceleration for video processing.
 *
 * @returns {boolean} True if hardware acceleration is supported, false otherwise.
 */
export const hasHardwareAcceleration = memoize(() => {
    const canvas = document.createElement("canvas");
    const gl =
        canvas.getContext("webgl2") ||
        canvas.getContext("webgl") ||
        canvas.getContext("experimental-webgl");
    if (!gl) {
        // WebGL support is typically required for hardware acceleration.
        return false;
    }
    const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
    if (debugInfo) {
        const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
        if (/swiftshader|llvmpipe|software/i.test(renderer)) {
            // These renderers indicate software-based rendering instead of hardware acceleration.
            return false;
        }
    }
    return true;
});

/**
 * Runs a reactive effect whenever the dependencies change. The effect receives
 * the current values returned by `dependencies`. If the effect returns a
 * cleanup function, it is run before the next execution.
 *
 * @template {object[]} T
 * @param {Object} options
 * @param {(...dependencies: any[]) => void | (() => void)} options.effect The
 *        effect callback. May return a cleanup function.
 * @param {(...args: [...T]) => Object|Array} options.dependencies Returns the
 *        values to track, as an array or an object. The effect is called only
 *        if these values change.
 * @param {[...T]} options.reactiveTargets Objects that the effect depends on.
 */
export function effectWithCleanup({ effect: effectFn, dependencies, reactiveTargets }) {
    let cleanup;
    let prevDependencies;
    effect((...deps) => {
        const nextDependencies = dependencies(...deps);
        const changed =
            !prevDependencies ||
            (Array.isArray(nextDependencies)
                ? nextDependencies.some((v, i) => v !== prevDependencies[i])
                : Object.keys(nextDependencies).some(
                      (key) => nextDependencies[key] !== prevDependencies[key],
                  ));
        if (changed) {
            prevDependencies = Array.isArray(nextDependencies)
                ? [...nextDependencies]
                : { ...nextDependencies };
            cleanup?.();
            cleanup = Array.isArray(nextDependencies)
                ? effectFn(...nextDependencies)
                : effectFn({ ...nextDependencies });
        }
    }, reactiveTargets);
}

/**
 * A thin wrapper around `effectWithCleanup` that debounces the cleanup phase:
 * setup runs immediately when activated, while cleanup is delayed until the
 * predicate remains false for `delay` ms.
 *
 * Setup is executed again only after cleanup has completed, ensuring symmetry
 * between setup and cleanup.
 *
 * @template T - type of reactive targets
 * @template D - type of dependencies
 * @param {Object} options
 * @param {(dependencies: D) => (() => void)} options.effect Function called
 * when the predicate becomes true and the effect is not active. Receives the
 * values returned by `dependencies`.
 * @param {number} options.delay Debounce delay in milliseconds before running
 * cleanup.
 * @param {(...targets: T) => D} options.dependencies Function returning an
 * object of values tracked by the effect; passed to `effect`.
 * @param {(...targets: T) => boolean} options.predicate Function returning a
 * boolean to determine whether the effect should be activated.
 * @param {[...T]} options.reactiveTargets Array of reactive objects that the
 * effect depends on.
 */
export function effectWithDebouncedCleanup({
    delay,
    dependencies,
    effect: effectFn,
    predicate,
    reactiveTargets,
}) {
    let timeout;
    let active = false;
    let cleanup;
    effectWithCleanup({
        effect(ctx) {
            const { predicate, ...deps } = ctx;
            if (!predicate) {
                return;
            }
            clearTimeout(timeout);
            if (!active) {
                cleanup = effectFn(deps);
                active = true;
            }
            return () => {
                timeout = setTimeout(() => {
                    cleanup();
                    active = false;
                }, delay);
            };
        },
        dependencies: (...targets) => ({
            predicate: predicate(...targets),
            ...dependencies(...targets),
        }),
        reactiveTargets,
    });
}

/**
 * @param {HTMLElement} targetNode
 * @param {string} bundleName
 */
export async function loadCssFromBundle(targetNode, bundleName) {
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
    } catch (e) {
        if (e instanceof AssetsLoadingError && e.cause instanceof TypeError) {
            // an AssetsLoadingError caused by a TypeError means the browser
            // cancelled the fetch, e.g. the user navigated away and the iframe
            // was unloaded: a normal situation, not worth reporting.
            return new Promise(() => {});
        } else {
            throw e;
        }
    }
}

/**
 * Serialize calls: while one call is running, a newly submitted one waits, and
 * any call queued behind it is superseded (its promise resolves with
 * `undefined`) so only the latest queued work runs.
 *
 * Not an OWL hook despite its former `useSequential` name: it registers no
 * lifecycle hook and must be callable outside `setup()` — it is used as a
 * `Record` field initializer (@see core/common/thread_model.js
 * `_loadAroundSequential`), where a real hook would throw.
 *
 * @returns {(func: () => Promise<any>) => Promise<any>}
 */
export function makeSequential() {
    let inProgress = false;
    let nextFunction;
    let nextResolve;
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
    return (func) => {
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
