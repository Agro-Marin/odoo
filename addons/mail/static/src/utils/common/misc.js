/** @odoo-module native */
import { observeKey } from "@mail/model/store";
import { AssetsLoadingError, getBundle } from "@web/core/assets";
import { memoize } from "@web/core/utils/functions";
import { effect } from "@web/core/utils/reactive";
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
 * Install computed properties on a plain object.
 *
 * The setter is a deliberate no-op rather than absent: the objects this is used
 * on are handed to OWL (as child sub-env), and a getter-only property throws on
 * assignment under strict mode as soon as anything copies or proxies the
 * object. Writes are meant to be ignored, not to fail.
 *
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

/** @type {{ isInTest: boolean }} */
export const mailGlobal = {
    isInTest: false,
};

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
 * Run `callback` whenever `key` of the reactive `target` changes.
 *
 * The subscription itself is {@link observeKey}; this is the eager form, which
 * re-observes and then reacts. Keeping one implementation matters more than it
 * looks: the two copies this replaced had already drifted, and only one of them
 * survived being reached after its disposer ran.
 *
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
                cleanup?.();
                cleanup = Array.isArray(nextDependencies)
                    ? effectFn(...nextDependencies)
                    : effectFn({ ...nextDependencies });
            }
        },
        reactiveTargets,
    );
}

/**
 * @template {object} T - type of one reactive target
 * @template {Object<string, any>} D - type of dependencies
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
                cleanup = effectFn(/** @type {D} */ (deps));
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
            // A TypeError from the fetch layer means the network went away --
            // in practice, the page is being torn down. Returning a promise
            // that never settles parks the caller instead of letting it carry
            // on against a document that is going away. It is deliberate, and
            // it does mean anything awaiting this never resumes.
            return new Promise(() => {});
        } else {
            throw e;
        }
    }
}

/**
 * Serialise calls, keeping only the most recent pending one.
 *
 * At most two calls are ever live: the one running and the one queued behind
 * it. A third supersedes the queued one, whose function is **never invoked**
 * and whose promise resolves with `undefined` — indistinguishable, to its
 * awaiter, from a call that ran and returned nothing. That is the intended
 * contract for the typeahead-shaped callers this has (search, mention and gif
 * pickers, sub-channel and attachment panels, loadAround), where only the
 * latest request is worth issuing; it is pinned by "isSequential doesn't
 * execute intermediate call." in mail_utils.test.js. Do not await one of these
 * expecting the work to have happened.
 *
 * @returns {(func: () => Promise<any>) => Promise<any>}
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
