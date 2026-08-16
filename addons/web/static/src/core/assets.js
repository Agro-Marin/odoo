// @ts-check
/** @odoo-module native */

/** @module @web/core/assets */

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
    injectedImportMapKeys: new Map(),
    crossDocImportMapKeys: new WeakMap(),
    crossDocLoadSeq: 0,
}));

export const globalBundleCache = __odoo_assets_state__.globalBundleCache;
export const assetCacheByDocument = __odoo_assets_state__.assetCacheByDocument;
const crossDocESMBundleCache = __odoo_assets_state__.crossDocESMBundleCache;
const injectedImportMapKeys = __odoo_assets_state__.injectedImportMapKeys;
const crossDocImportMapKeys = __odoo_assets_state__.crossDocImportMapKeys;

/**
 * A specifier already mapped in a document cannot be remapped: a later import
 * map carrying the same key has that rule dropped ("An import map rule for
 * specifier X was removed, as it conflicted with an existing rule"). So every
 * document gets its own record of what has been mapped in it.
 *
 * The record is specifier -> TARGET, not a bare set of names. Whether a
 * specifier is already claimed and whether it is claimed by the URL this bundle
 * wants are different questions, and only the second one predicts whether
 * `import(specifier)` returns the right module. Tracking names alone made the
 * two indistinguishable, so a bundle whose specifier had been claimed by
 * someone else's bridge silently imported that bridge instead — see
 * `resolveSpecifierTarget`.
 *
 * @param {Document} targetDoc
 * @returns {Map<string, string>}
 */
function getInjectedImportMapKeys(targetDoc) {
    if (targetDoc === document || targetDoc.defaultView === window) {
        return injectedImportMapKeys;
    }
    let keys = crossDocImportMapKeys.get(targetDoc);
    if (!keys) {
        keys = new Map();
        crossDocImportMapKeys.set(targetDoc, keys);
    }
    return keys;
}

/**
 * Absolute form of an import-map target, so two spellings of one URL compare
 * equal. `data:` targets are already absolute and `URL` leaves them alone.
 *
 * @param {string} url
 * @param {Document} targetDoc
 * @returns {string}
 */
function absoluteTarget(url, targetDoc) {
    try {
        return new URL(url, targetDoc.baseURI).href;
    } catch {
        return url;
    }
}

/**
 * @param {Document} targetDoc
 * @param {Map<string, string>} [keys]
 * @returns {number}
 */
function seedInjectedImportMapKeys(targetDoc, keys) {
    const head = targetDoc.head || targetDoc.documentElement;
    if (!head) {
        return 0;
    }
    const injected = keys ?? getInjectedImportMapKeys(targetDoc);
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
                for (const [spec, url] of Object.entries(imports)) {
                    // First rule wins, in the record exactly as in the browser.
                    if (!injected.has(spec)) {
                        injected.set(spec, absoluteTarget(url, targetDoc));
                        seeded++;
                    }
                }
            }
        } catch {}
    }
    return seeded;
}

/**
 * What to hand `import()` for one of a bundle's own specifiers.
 *
 * Normally the specifier itself: the import map resolves it. But when the
 * document already maps it somewhere else, no import map can take it back —
 * the browser drops the conflicting rule — so importing the specifier would
 * return whichever module claimed the name first. That is how a bundle came to
 * load against a bridge shim whose producer was never on the page, giving
 * `undefined` for every export.
 *
 * Importing the URL directly sidesteps the map for this one module, and
 * registering the result under the specifier repairs the rest of the graph:
 * the bridges other modules resolve to read `odoo.loader.modules.get(spec)`.
 *
 * @param {string} specifier
 * @param {Record<string, string> | null | undefined} importMap
 * @param {Map<string, string>} injected
 * @param {Document} targetDoc
 * @returns {{ target: string, conflict: boolean }}
 */
function resolveSpecifierTarget(specifier, importMap, injected, targetDoc) {
    const wanted = importMap?.[specifier];
    if (!wanted) {
        return { target: specifier, conflict: false };
    }
    const claimed = injected.get(specifier);
    const wantedAbs = absoluteTarget(wanted, targetDoc);
    if (claimed === undefined || claimed === wantedAbs) {
        return { target: specifier, conflict: false };
    }
    return { target: wantedAbs, conflict: true };
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
    let cacheMap = assetCacheByDocument.get(targetDoc);
    if (!cacheMap) {
        cacheMap = new Map();
        assetCacheByDocument.set(targetDoc, cacheMap);
        // Seeded on creation rather than for `document` alone: an iframe
        // carries its own assets in its own markup -- a website preview and a
        // mass-mailing frame both do -- and loading a bundle into it used to
        // append a second copy of every asset it already had, running each of
        // those scripts a second time in that document.
        seedFromDocument(targetDoc, cacheMap);
    }
    return cacheMap;
}

/**
 * @param {Document} targetDoc
 * @param {Map<string, Promise<any>>} cacheMap
 */
function seedFromDocument(targetDoc, cacheMap) {
    const head = targetDoc.head;
    if (!head) {
        return;
    }
    // Records what the page itself delivered, so nobody re-requests it. An
    // entry that is already there tracks a load *we* started and may still be
    // running -- `loadJS` appends its script to the same head, so this would
    // find it and overwrite the pending promise with a resolved one, telling
    // the next caller the asset was ready while it was still executing.
    const seed = (/** @type {string | null} */ url) => {
        if (url && !cacheMap.has(url)) {
            cacheMap.set(url, Promise.resolve());
        }
    };
    for (const script of head.querySelectorAll("script[src]")) {
        seed(script.getAttribute("src"));
    }
    for (const link of head.querySelectorAll("link[rel=stylesheet][href]")) {
        seed(link.getAttribute("href"));
    }
}

/**
 * Re-seed a document whose ``<head>`` has grown since its cache was created.
 *
 * @param {Document} targetDoc
 */
function computeBundleCacheMap(targetDoc) {
    seedFromDocument(targetDoc, getAssetCache(targetDoc));
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
 * @param {() => void} [onPageHideCleanup]
 * @param {(error: Error) => any} [onInterrupt]
 */
const onLoadAndError = (el, onLoad, onError, onPageHideCleanup, onInterrupt) => {
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

export const assets = {
    retries: {
        count: 3,
        delay: 5000,
        extraDelay: 2500,
    },

    /**
     * @param {string} bundleName
     * @returns {Promise<BundleFileNames>}
     */
    getBundle(bundleName) {
        const cacheMap = getGlobalBundleCache();
        if (cacheMap.has(bundleName)) {
            log("getBundle:cache-hit", bundleName);
            return /** @type {Promise<BundleFileNames>} */ (cacheMap.get(bundleName));
        }
        log("getBundle:fetch", bundleName);
        const url = new URL(`/web/bundle/${bundleName}`, browser.location.origin);
        for (const [key, value] of Object.entries(session.bundle_params || {})) {
            url.searchParams.set(key, value);
        }
        const promise = (async () => {
            const response = await browser.fetch(url);
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
     * @param {string} bundleName
     * @param {Object} options
     * @param {Document} [options.targetDoc=document]
     * @param {Boolean} [options.css=true]
     * @param {Boolean} [options.js=true]
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
     * @param {string[]} specifiers
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
                /** @type {string[]} */
                const conflicts = [];
                for (const [spec, url] of Object.entries(importMap)) {
                    const claimed = injectedImportMapKeys.get(spec);
                    const wanted = absoluteTarget(url, document);
                    if (claimed === undefined) {
                        freshEntries[spec] = url;
                        injectedImportMapKeys.set(spec, wanted);
                    } else if (claimed === wanted) {
                        nDup++;
                    } else {
                        // Not re-mappable, and not the same module: the bundle's
                        // own import below goes to the URL instead.
                        conflicts.push(spec);
                    }
                }
                const nFresh = Object.keys(freshEntries).length;
                log(
                    "loadESMBundle:importMap filter",
                    "fresh=",
                    nFresh,
                    "dup=",
                    nDup,
                    "conflict=",
                    conflicts.length,
                    "total=",
                    nFresh + nDup + conflicts.length,
                );
                if (conflicts.length) {
                    // Loud: a conflict means some earlier bundle mapped this
                    // specifier somewhere else, and every module that imports it
                    // by name — including any bridge — still gets that one.
                    log("loadESMBundle:specifier already claimed elsewhere", conflicts);
                }
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
                    const { target } = resolveSpecifierTarget(
                        specifier,
                        importMap,
                        injectedImportMapKeys,
                        document,
                    );
                    const mod = await import(target);
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
        // Same filtering the same-document branch does: a second bundle loaded
        // into this iframe repeats every specifier the first one mapped, and
        // re-declaring one is not an error -- the browser silently drops the
        // new rule and keeps the old target.
        const injected = getInjectedImportMapKeys(targetDoc);
        seedInjectedImportMapKeys(targetDoc, injected);
        /** @type {Record<string, any>} */
        const freshEntries = {};
        let nDup = 0;
        /** @type {string[]} */
        const conflicts = [];
        for (const [spec, url] of Object.entries(extraMap)) {
            const claimed = injected.get(spec);
            const wanted = absoluteTarget(url, targetDoc);
            if (claimed === undefined) {
                freshEntries[spec] = url;
                injected.set(spec, wanted);
            } else if (claimed === wanted) {
                nDup++;
            } else {
                conflicts.push(spec);
            }
        }
        if (conflicts.length) {
            log("loadESMBundle:crossDoc specifier already claimed", conflicts);
        }
        const nFresh = Object.keys(freshEntries).length;
        if (nFresh) {
            log(
                "loadESMBundle:crossDoc injecting extra import map entries=",
                nFresh,
                "dup=",
                nDup,
            );
            const mapEl = targetDoc.createElement("script");
            mapEl.type = "importmap";
            mapEl.textContent = JSON.stringify({ imports: freshEntries });
            (targetDoc.head || targetDoc.documentElement).appendChild(mapEl);
        }
        const token = ++__odoo_assets_state__.crossDocLoadSeq;
        const doneEvent = `__odoo_esm_bundle_loaded_${token}`;
        const errorEvent = `__odoo_esm_bundle_error_${token}`;
        // `[specifier, whatToImport]` rather than the bare specifier: for a
        // specifier this document already maps elsewhere, importing the name
        // returns whatever claimed it first, so the URL is passed instead and
        // the result is still registered under the specifier. Same reasoning as
        // `resolveSpecifierTarget` in the same-document branch.
        const importPairs = specifiers.map((specifier) => [
            specifier,
            resolveSpecifierTarget(specifier, extraMap, injected, targetDoc).target,
        ]);
        const scriptText = `
            (async () => {
                try {
                    const specs = ${JSON.stringify(importPairs)};
                    const pairs = await Promise.all(
                        specs.map(async ([s, t]) => [s, await import(t)])
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
     * @param {string} url
     * @param {{ retryCount?: number, targetDoc?: Document }} [options]
     * @returns {Promise<void>}
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
                        // Detached on *every* failure, not just before a retry.
                        // A dead `<link>` left in the head is not merely litter:
                        // `seedFromDocument` walks `link[rel=stylesheet][href]`
                        // and seeds each href it finds with a resolved promise,
                        // so the next `loadCSS` for this url would be told the
                        // stylesheet was already delivered.
                        linkEl.remove();
                        const retryable = !url.includes("/web/assets/");
                        if (retryable && attempt < assets.retries.count) {
                            const delay =
                                assets.retries.delay +
                                assets.retries.extraDelay * attempt;
                            await new Promise((res) => browser.setTimeout(res, delay));
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
     * @param {string} url
     * @param {{ targetDoc?: Document }} [options]
     * @returns {Promise<void>}
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
                    // See `loadCSS`: a failed `<script src>` left in the head is
                    // what `seedFromDocument` would later read as "already
                    // delivered", masking the failure from the next caller.
                    scriptEl.remove();
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
