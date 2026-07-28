// @ts-check
/** @odoo-module native */

/** @module @web/core/assets - Lazy-loads CSS/JS asset bundles into documents with caching */

import { Component, onWillStart, whenReady, xml } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

import {
    buildBridgeModuleSource,
    isLoaderBridgeUrl,
    specToModuleUrl,
    toDataModuleUrl,
} from "./module_bridge.js";
import { registry } from "./registry.js";
import { makeAssetLog } from "./utils/asset_log.js";
import { globalSingleton } from "./utils/global_singleton.js";

const log = makeAssetLog("js");

/**
 * @typedef {{
 *  cssLibs: string[];
 *  jsLibs: string[];
 *  esmSpecifiers: string[] | null;
 *  esmImportMap: Record<string, string> | null;
 * }} BundleFileNames
 */

const __odoo_assets_state__ = globalSingleton("assets", () => ({
    globalBundleCache: new Map(),
    assetCacheByDocument: new WeakMap(),
    crossDocESMBundleCache: new WeakMap(),
    injectedImportMapKeys: new Set(),
    crossDocLoadSeq: 0,
}));

export const globalBundleCache = __odoo_assets_state__.globalBundleCache;
export const assetCacheByDocument = __odoo_assets_state__.assetCacheByDocument;
export const crossDocESMBundleCache = __odoo_assets_state__.crossDocESMBundleCache;
const injectedImportMapKeys = __odoo_assets_state__.injectedImportMapKeys;

/**
 * Pre-seed ``injectedImportMapKeys`` from the document's existing
 * ``<script type="importmap">`` tags. The initial page import map is rendered
 * server-side (``ir_qweb._get_esm_asset_nodes``) and already contains every
 * specifier of ``web.assets_web``'s dynamic child bundles (tour, spreadsheet,
 * html_editor, mail, etc.); without this seed, the first
 * ``loadBundle("web_tour.interactive")`` call would re-inject them and
 * Chromium would warn for each one.
 *
 * @param {Document} targetDoc
 * @returns {number} number of specifiers seeded
 */
function seedInjectedImportMapKeys(targetDoc) {
    const head = targetDoc.head || targetDoc.documentElement;
    if (!head) {
        return 0;
    }
    let seeded = 0;
    for (const script of head.querySelectorAll('script[type="importmap"]')) {
        const text = script.textContent || "";
        if (!text.trim()) {
            continue;
        }
        try {
            const parsed = JSON.parse(text);
            const imports = parsed && parsed.imports;
            if (imports && typeof imports === "object") {
                for (const spec of Object.keys(imports)) {
                    if (!injectedImportMapKeys.has(spec)) {
                        injectedImportMapKeys.add(spec);
                        seeded++;
                    }
                }
            }
        } catch {
            // Malformed JSON is the server's problem — the import map
            // wouldn't work anyway.  Don't abort the seed for other tags.
        }
    }
    return seeded;
}

/** @returns {Map<string, Promise<any>>} */
function getGlobalBundleCache() {
    return globalBundleCache;
}

/**
 * @param {Document} targetDoc
 * @returns {Map<string, Promise<any>>}
 */
function getAssetCache(targetDoc) {
    if (!assetCacheByDocument.has(targetDoc)) {
        assetCacheByDocument.set(targetDoc, new Map());
    }
    return assetCacheByDocument.get(targetDoc);
}

/**
 * Seed the per-document asset cache with the script/link URLs already
 * present in the document, so that ``loadJS``/``loadCSS`` (which dedupe
 * against that same cache) don't re-inject — and re-execute — assets
 * the server already rendered into the initial HTML.
 *
 * @param {Document} targetDoc
 */
function computeBundleCacheMap(targetDoc) {
    const cacheMap = getAssetCache(targetDoc);
    for (const script of targetDoc.head.querySelectorAll("script[src]")) {
        cacheMap.set(
            /** @type {string} */ (script.getAttribute("src")),
            Promise.resolve(),
        );
    }
    for (const link of targetDoc.head.querySelectorAll("link[rel=stylesheet][href]")) {
        cacheMap.set(
            /** @type {string} */ (link.getAttribute("href")),
            Promise.resolve(),
        );
    }
}

whenReady(() => {
    computeBundleCacheMap(document);
    const seeded = seedInjectedImportMapKeys(document);
    log("whenReady:seeded-import-map-keys", seeded);
});

/**
 * @param {HTMLLinkElement | HTMLScriptElement} el
 * @param {(event: Event) => any} onLoad
 * @param {(error: Error) => any} onError
 * @param {() => void} [onPageHideCleanup] invoked when the page hides before
 *  the asset settles (bfcache hazard) — evict cache entries here
 * @param {(error: Error) => any} [onInterrupt] settles the caller's promise when
 *  the page hides mid-load. Separate from `onError` because the caller's error
 *  path may retry, and an interrupted load must not be retried — it must reject.
 */
const onLoadAndError = (el, onLoad, onError, onPageHideCleanup, onInterrupt) => {
    // The interrupt guard has to watch the window the ELEMENT lives in. For a
    // cross-document load (`targetDoc` = an iframe document) that is not the
    // top-level window, so watching `window` never fired: the iframe could
    // unload mid-load, leaving the caller's promise pending forever and the
    // cache entry poisoned with it.
    const view = el.ownerDocument?.defaultView ?? window;

    const onLoadListener = (/** @type {Event} */ event) => {
        removeListeners();
        onLoad(event);
    };

    const onErrorListener = (/** @type {Event} */ error) => {
        removeListeners();
        onError(/** @type {any} */ (error));
    };

    const onPageHide = () => {
        removeListeners();
        onPageHideCleanup?.();
        onInterrupt?.(
            new AssetsLoadingError(
                `The loading of ${el.getAttribute("src") || el.getAttribute("href")} was interrupted: the page was hidden`,
            ),
        );
    };

    const removeListeners = () => {
        el.removeEventListener("load", onLoadListener);
        el.removeEventListener("error", onErrorListener);
        view.removeEventListener("pagehide", onPageHide);
    };

    el.addEventListener("load", onLoadListener);
    el.addEventListener("error", onErrorListener);
    view.addEventListener("pagehide", onPageHide);
};

/**
 * @param {string} bundleName
 * @returns {Promise<BundleFileNames>}
 */
export function getBundle(bundleName) {
    return assets.getBundle(bundleName);
}

/**
 * @param {string} bundleName
 * @param {{ targetDoc?: Document, css?: boolean, js?: boolean }} [options]
 * @returns {Promise<void[]>}
 */
export function loadBundle(bundleName, options) {
    return assets.loadBundle(bundleName, options);
}

/**
 * @param {string} url
 * @param {{ targetDoc?: Document }} [options]
 * @returns {Promise<void>}
 */
export function loadJS(url, options) {
    return assets.loadJS(url, options);
}

/**
 * @param {string} url
 * @param {{ retryCount?: number, targetDoc?: Document }} [options]
 * @returns {Promise<void>}
 */
export function loadCSS(url, options) {
    return assets.loadCSS(url, options);
}

export class AssetsLoadingError extends Error {}

/**
 * Drop ``url`` from ``cacheMap``, but only if it still holds the promise the
 * caller owns.
 *
 * Every eviction here races a replacement: an entry is removed on failure or on
 * a page-hide interrupt, and a later ``loadJS``/``loadCSS`` for the same url
 * immediately installs a fresh promise — while the older load's listeners are
 * still attached, because ``pagehide`` fires for every live element at once.
 * An unconditional ``delete`` then evicts the NEWER, healthy entry, and the
 * asset is re-injected (and re-executed) on the next request.
 *
 * ``getOwn`` is a thunk because the promise is not yet bound when the listeners
 * are registered (it is the value being constructed).
 *
 * @param {Map<string, Promise<any>>} cacheMap
 * @param {string} url
 * @param {() => Promise<any>} getOwn
 */
function evictIfCurrent(cacheMap, url, getOwn) {
    if (cacheMap.get(url) === getOwn()) {
        cacheMap.delete(url);
    }
}

registry
    .category("lazy_components")
    .addValidation((entry) => entry?.prototype instanceof Component);

/**
 * Utility component that loads an asset bundle before instanciating a component
 */
export class LazyComponent extends Component {
    static template = xml`<t t-component="Component" t-props="componentProps"/>`;
    static props = {
        Component: String,
        bundle: String,
        props: { type: [Object, Function], optional: true },
    };
    setup() {
        onWillStart(async () => {
            await loadBundle(this.props.bundle);
            this.Component = registry
                .category("lazy_components")
                .get(this.props.Component);
        });
    }

    get componentProps() {
        return typeof this.props.props === "function"
            ? this.props.props()
            : this.props.props;
    }
}

/**
 * Exported only so tests can override behavior; other modules should use the
 * standalone functions above instead of the methods below directly.
 */
export const assets = {
    retries: {
        count: 3,
        delay: 5000,
        extraDelay: 2500,
    },

    /**
     * Get the files information as descriptor object from a public asset template.
     *
     * @param {string} bundleName Name of the bundle containing the list of files
     * @returns {Promise<BundleFileNames>}
     */
    getBundle(bundleName) {
        const cacheMap = getGlobalBundleCache();
        if (cacheMap.has(bundleName)) {
            log("getBundle:cache-hit", bundleName);
            return /** @type {Promise<BundleFileNames>} */ (cacheMap.get(bundleName));
        }
        log("getBundle:fetch", bundleName);
        const url = new URL(`/web/bundle/${bundleName}`, location.origin);
        for (const [key, value] of Object.entries(session.bundle_params || {})) {
            url.searchParams.set(key, value);
        }
        const promise = (async () => {
            const response = await fetch(url);
            if (!response.ok) {
                throw new AssetsLoadingError(
                    `The loading of ${url} failed with HTTP status ${response.status}`,
                );
            }
            const cssLibs = [];
            const jsLibs = [];
            let esmSpecifiers = null;
            let esmImportMap = null;
            const result = await response.json();
            if (!result || typeof result !== "object") {
                throw new AssetsLoadingError(
                    `The loading of ${url} failed: unexpected bundle descriptor`,
                );
            }
            if (result.is_esm) {
                esmSpecifiers = result.specifiers || [];
                esmImportMap = result.import_map || null;
                if (result.template_url) {
                    esmSpecifiers.push(result.template_url);
                }
                for (const { src, type } of Object.values(result.files || {})) {
                    if (type === "link" && src) {
                        cssLibs.push(src);
                    } else if (type === "script" && src && !src.includes(".esm.")) {
                        jsLibs.push(src);
                    }
                }
            } else {
                for (const { src, type } of Object.values(result)) {
                    if (type === "link" && src) {
                        cssLibs.push(src);
                    } else if (type === "script" && src && !src.includes(".esm.")) {
                        jsLibs.push(src);
                    }
                }
            }
            log("getBundle:done", bundleName, {
                cssLibs: cssLibs.length,
                jsLibs: jsLibs.length,
                esmSpecifiers: esmSpecifiers?.length ?? null,
                importMapEntries: esmImportMap
                    ? Object.keys(esmImportMap).length
                    : null,
            });
            return { cssLibs, jsLibs, esmSpecifiers, esmImportMap };
        })().catch((reason) => {
            evictIfCurrent(cacheMap, bundleName, () => promise);
            log("getBundle:error", bundleName, reason);
            if (reason instanceof AssetsLoadingError) {
                throw reason;
            }
            throw new AssetsLoadingError(`The loading of ${url} failed`, {
                cause: reason,
            });
        });
        cacheMap.set(bundleName, promise);
        return promise;
    },

    /**
     * Loads the given js/css libraries and asset bundles. Already-loaded
     * libraries or assets are not reloaded.
     *
     * @param {string} bundleName
     * @param {Object} options
     * @param {Document} [options.targetDoc=document] document to which the bundle will be applied (e.g. iframe document)
     * @param {Boolean} [options.css=true] apply bundle css on targetDoc
     * @param {Boolean} [options.js=true] apply bundle js on targetDoc
     * @returns {Promise<void[]>}
     */
    async loadBundle(bundleName, { targetDoc = document, css = true, js = true } = {}) {
        if (typeof bundleName !== "string") {
            throw new Error(
                `loadBundle(bundleName:string) accepts only bundleName argument as a string ! Not ${JSON.stringify(
                    bundleName,
                )} as ${typeof bundleName}`,
            );
        }
        log(
            "loadBundle:start",
            bundleName,
            "css=",
            css,
            "js=",
            js,
            "crossDoc=",
            targetDoc !== document,
        );
        const { cssLibs, jsLibs, esmSpecifiers, esmImportMap } =
            await getBundle(bundleName);
        const promises = [];
        if (css && cssLibs) {
            promises.push(...cssLibs.map((url) => assets.loadCSS(url, { targetDoc })));
        }
        if (js && esmSpecifiers) {
            promises.push(
                assets.loadESMBundle(esmSpecifiers, {
                    targetDoc,
                    importMap: esmImportMap,
                }),
            );
        }
        if (js && jsLibs && jsLibs.length) {
            promises.push(...jsLibs.map((url) => assets.loadJS(url, { targetDoc })));
        }
        const result = await Promise.all(promises);
        log("loadBundle:done", bundleName, "promises=", promises.length);
        return result;
    },

    /**
     * Loads native ESM modules via dynamic import() and registers them in the
     * target document's ``odoo.loader.modules`` for runtime access by dynamic
     * callers. When ``targetDoc`` is foreign (e.g. an iframe), the imports MUST
     * run in that document's context so specifiers resolve via its import map
     * and modules land in its own ``odoo.loader`` — done by injecting a
     * ``<script type="module">`` into ``targetDoc`` to perform the imports
     * in-context.
     *
     * @param {string[]} specifiers module specifiers to import
     * @param {{ targetDoc?: Document, importMap?: Record<string, string> | null }} [options]
     * @returns {Promise<void>}
     */
    async loadESMBundle(specifiers, { targetDoc = document, importMap = null } = {}) {
        log(
            "loadESMBundle:start",
            "specs=",
            specifiers.length,
            "importMap=",
            importMap ? Object.keys(importMap).length : 0,
            "crossDoc=",
            !(targetDoc === document || targetDoc.defaultView === window),
        );
        if (targetDoc === document || targetDoc.defaultView === window) {
            if (importMap) {
                seedInjectedImportMapKeys(document);
                /** @type {Record<string, any>} */
                const freshEntries = {};
                let nDup = 0;
                for (const [spec, url] of Object.entries(importMap)) {
                    if (!injectedImportMapKeys.has(spec)) {
                        freshEntries[spec] = url;
                        injectedImportMapKeys.add(spec);
                    } else {
                        nDup++;
                    }
                }
                const nFresh = Object.keys(freshEntries).length;
                log(
                    "loadESMBundle:importMap filter",
                    "fresh=",
                    nFresh,
                    "dup=",
                    nDup,
                    "total=",
                    nFresh + nDup,
                );
                if (nFresh) {
                    const mapEl = document.createElement("script");
                    mapEl.type = "importmap";
                    mapEl.textContent = JSON.stringify({ imports: freshEntries });
                    (document.head || document.documentElement).appendChild(mapEl);
                    log("loadESMBundle:injected fresh import map entries=", nFresh);
                }
            }
            const results = await Promise.all(
                specifiers.map(async (specifier) => {
                    const mod = await import(specifier);
                    const mappedUrl = importMap?.[specifier];
                    if (mappedUrl && typeof mod.__setImplUrl === "function") {
                        await mod.__setImplUrl(
                            new URL(mappedUrl, document.baseURI).href,
                        );
                    }
                    return [specifier, mod];
                }),
            );
            const modules = Object.fromEntries(results);
            if (/** @type {any} */ (globalThis).odoo?.loader?.registerNativeModules) {
                odoo.loader.registerNativeModules(modules);
                log(
                    "loadESMBundle:registered",
                    specifiers.length,
                    "modules into odoo.loader",
                );
            } else {
                log("loadESMBundle:warn no odoo.loader.registerNativeModules");
            }
            return;
        }
        const cacheKey = JSON.stringify(specifiers);
        if (!crossDocESMBundleCache.has(targetDoc)) {
            crossDocESMBundleCache.set(targetDoc, new Map());
        }
        const bundleCache = crossDocESMBundleCache.get(targetDoc);
        if (bundleCache.has(cacheKey)) {
            log("loadESMBundle:crossDoc cache-hit", "specs=", specifiers.length);
            return bundleCache.get(cacheKey);
        }
        const targetWin = /** @type {any} */ (targetDoc.defaultView);
        const serverMap = importMap || {};
        /** @type {Record<string, any>} */
        const extraMap = {};
        const loadedModules = targetWin.odoo?.loader?.modules;
        if (loadedModules && typeof loadedModules.get === "function") {
            const specs =
                typeof loadedModules.keys === "function"
                    ? Array.from(loadedModules.keys())
                    : [];
            for (const spec of specs) {
                if (!spec || typeof spec !== "string" || spec.startsWith("@odoo/")) {
                    continue;
                }
                const mod = loadedModules.get(spec);
                if (!mod || typeof mod !== "object") {
                    continue;
                }
                const bridgeTarget = isLoaderBridgeUrl(serverMap[spec])
                    ? serverMap[spec]
                    : toDataModuleUrl(buildBridgeModuleSource(spec, Object.keys(mod)));
                if (serverMap[spec] === undefined) {
                    extraMap[spec] = bridgeTarget;
                }
                const url = specToModuleUrl(spec);
                if (url && serverMap[url] === undefined) {
                    extraMap[url] = bridgeTarget;
                }
            }
        }
        Object.assign(extraMap, serverMap);
        if (Object.keys(extraMap).length) {
            log(
                "loadESMBundle:crossDoc injecting extra import map entries=",
                Object.keys(extraMap).length,
            );
            const mapEl = targetDoc.createElement("script");
            mapEl.type = "importmap";
            mapEl.textContent = JSON.stringify({ imports: extraMap });
            (targetDoc.head || targetDoc.documentElement).appendChild(mapEl);
        }
        const token = ++__odoo_assets_state__.crossDocLoadSeq;
        const doneEvent = `__odoo_esm_bundle_loaded_${token}`;
        const errorEvent = `__odoo_esm_bundle_error_${token}`;
        const scriptText = `
            (async () => {
                try {
                    const specs = ${JSON.stringify(specifiers)};
                    const pairs = await Promise.all(
                        specs.map(async (s) => [s, await import(s)])
                    );
                    const modules = Object.fromEntries(pairs);
                    if (window.odoo?.loader?.registerNativeModules) {
                        window.odoo.loader.registerNativeModules(modules);
                    }
                    window.dispatchEvent(new Event(${JSON.stringify(doneEvent)}));
                } catch (err) {
                    window.dispatchEvent(new CustomEvent(${JSON.stringify(errorEvent)}, { detail: err }));
                }
            })();
        `;
        const scriptEl = targetDoc.createElement("script");
        scriptEl.type = "module";
        scriptEl.textContent = scriptText;
        const win = /** @type {Window} */ (targetDoc.defaultView);
        const settlePromise = new Promise((resolve, reject) => {
            const settle = (/** @type {() => void} */ fn) => {
                win.removeEventListener(doneEvent, onDone);
                win.removeEventListener(errorEvent, onError);
                win.removeEventListener("pagehide", onPageHide);
                scriptEl.removeEventListener("error", onScriptError);
                fn();
            };
            const onDone = () => settle(() => resolve(undefined));
            const onError = (/** @type {Event} */ e) =>
                settle(() =>
                    reject(
                        /** @type {CustomEvent} */ (e).detail ||
                            new Error(`loadESMBundle failed`),
                    ),
                );
            const onScriptError = (/** @type {Event} */ error) =>
                settle(() =>
                    reject(
                        new AssetsLoadingError(`The loading of an ESM bundle failed`, {
                            cause: error,
                        }),
                    ),
                );
            const onPageHide = () =>
                settle(() =>
                    reject(
                        new AssetsLoadingError(
                            `The loading of an ESM bundle was interrupted: the target document was unloaded`,
                        ),
                    ),
                );
            win.addEventListener(doneEvent, onDone);
            win.addEventListener(errorEvent, onError);
            win.addEventListener("pagehide", onPageHide);
            scriptEl.addEventListener("error", onScriptError);
            (targetDoc.head || targetDoc.documentElement).appendChild(scriptEl);
        });
        bundleCache.set(cacheKey, settlePromise);
        settlePromise.catch(() =>
            evictIfCurrent(bundleCache, cacheKey, () => settlePromise),
        );
        return settlePromise;
    },

    /**
     * Loads the given url as a stylesheet.
     *
     * @param {string} url the url of the stylesheet
     * @param {{ retryCount?: number, targetDoc?: Document }} [options]
     * @returns {Promise<void>} resolved when the stylesheet has been loaded
     */
    loadCSS(url, { retryCount = 0, targetDoc = document } = {}) {
        const cacheMap = getAssetCache(targetDoc);
        if (cacheMap.has(url)) {
            return /** @type {Promise<void>} */ (cacheMap.get(url));
        }
        /**
         * @param {number} attempt
         * @returns {Promise<void>}
         */
        const runAttempt = (attempt) => {
            if (attempt === 0) {
                log("loadCSS", url);
            } else {
                log("loadCSS:retry", url, "attempt=", attempt);
            }
            const linkEl = targetDoc.createElement("link");
            linkEl.setAttribute("href", url);
            linkEl.type = "text/css";
            linkEl.rel = "stylesheet";
            const attemptPromise = new Promise((resolve, reject) =>
                onLoadAndError(
                    linkEl,
                    resolve,
                    async (error) => {
                        const retryable = !url.includes("/web/assets/");
                        if (retryable && attempt < assets.retries.count) {
                            const delay =
                                assets.retries.delay +
                                assets.retries.extraDelay * attempt;
                            await new Promise((res) => browser.setTimeout(res, delay));
                            linkEl.remove();
                            runAttempt(attempt + 1).then(resolve, reject);
                        } else {
                            reject(
                                new AssetsLoadingError(`The loading of ${url} failed`, {
                                    cause: error,
                                }),
                            );
                        }
                    },
                    () => evictIfCurrent(cacheMap, url, () => promise),
                    reject,
                ),
            );
            targetDoc.head.appendChild(linkEl);
            return attemptPromise;
        };
        const promise = /** @type {Promise<void>} */ (
            runAttempt(retryCount).catch((reason) => {
                evictIfCurrent(cacheMap, url, () => promise);
                throw reason;
            })
        );
        cacheMap.set(url, promise);
        return promise;
    },

    /**
     * Loads the given url inside a script tag.
     *
     * @param {string} url the url of the script
     * @param {{ targetDoc?: Document }} [options]
     * @returns {Promise<void>} resolved when the script has been loaded
     */
    loadJS(url, { targetDoc = document } = {}) {
        const cacheMap = getAssetCache(targetDoc);
        if (cacheMap.has(url)) {
            return /** @type {Promise<void>} */ (cacheMap.get(url));
        }
        log("loadJS", url);
        const scriptEl = targetDoc.createElement("script");
        scriptEl.setAttribute("src", url);
        scriptEl.type = "text/javascript";
        scriptEl.async = false;
        const promise = new Promise((resolve, reject) =>
            onLoadAndError(
                scriptEl,
                resolve,
                (error) => {
                    evictIfCurrent(cacheMap, url, () => promise);
                    reject(
                        new AssetsLoadingError(`The loading of ${url} failed`, {
                            cause: error,
                        }),
                    );
                },
                () => evictIfCurrent(cacheMap, url, () => promise),
                reject,
            ),
        );
        cacheMap.set(url, promise);
        targetDoc.head.appendChild(scriptEl);
        return promise;
    },
};
