// @ts-check
/** @odoo-module native */

/** @module @web/core/assets - Lazy-loads CSS/JS asset bundles into documents with caching */

import { Component, onWillStart, whenReady, xml } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

import { registry } from "./registry.js";

/**
 * @typedef {{
 *  cssLibs: string[];
 *  jsLibs: string[];
 *  esmSpecifiers: string[] | null;
 * }} BundleFileNames
 */

export const globalBundleCache = new Map();
export const assetCacheByDocument = new WeakMap();

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
 * @param {Document} targetDoc
 */
function computeBundleCacheMap(targetDoc) {
    const cacheMap = getGlobalBundleCache();
    for (const script of targetDoc.head.querySelectorAll("script[src]")) {
        cacheMap.set(script.getAttribute("src"), Promise.resolve());
    }
    for (const link of targetDoc.head.querySelectorAll("link[rel=stylesheet][href]")) {
        cacheMap.set(link.getAttribute("href"), Promise.resolve());
    }
}

whenReady(() => computeBundleCacheMap(document));

/**
 * @param {HTMLLinkElement | HTMLScriptElement} el
 * @param {(event: Event) => any} onLoad
 * @param {(error: Error) => any} onError
 */
const onLoadAndError = (el, onLoad, onError) => {
    const onLoadListener = (event) => {
        removeListeners();
        onLoad(event);
    };

    const onErrorListener = (error) => {
        removeListeners();
        onError(error);
    };

    const removeListeners = () => {
        el.removeEventListener("load", onLoadListener);
        el.removeEventListener("error", onErrorListener);
    };

    el.addEventListener("load", onLoadListener);
    el.addEventListener("error", onErrorListener);

    window.addEventListener("pagehide", () => {
        removeListeners();
    }, { once: true });
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
 * This export is done only in order to modify the behavior of the exported
 * functions. This is done in order to be able to make a test environment.
 * Modules should only use the methods exported below.
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
            console.debug(`[assets] getBundle(${bundleName}): cache hit`);
            return cacheMap.get(bundleName);
        }
        const url = new URL(`/web/bundle/${bundleName}`, location.origin);
        for (const [key, value] of Object.entries(session.bundle_params || {})) {
            url.searchParams.set(key, value);
        }
        // The promise is stored in the cache synchronously (before it resolves)
        // so concurrent calls for the same bundle share a single fetch.
        const promise = (async () => {
            const response = await fetch(url);
            const cssLibs = [];
            const jsLibs = [];
            let esmSpecifiers = null;
            if (!response.bodyUsed) {
                const result = await response.json();
                if (result.is_esm) {
                    esmSpecifiers = result.specifiers || [];
                    // Inline ESM: read-only transaction couldn't save an
                    // ir.attachment.  Convert to a Blob URL so import()
                    // inherits the page's import map (data: URIs don't).
                    if (result.inline_esm) {
                        const blob = new Blob([result.inline_esm], { type: "text/javascript" });
                        esmSpecifiers.push(URL.createObjectURL(blob));
                    }
                    for (const { src, type } of Object.values(result.files || {})) {
                        if (type === "link" && src) {
                            cssLibs.push(src);
                        } else if (type === "script" && src) {
                            jsLibs.push(src);
                        }
                    }
                } else {
                    for (const { src, type } of Object.values(result)) {
                        if (type === "link" && src) {
                            cssLibs.push(src);
                        } else if (type === "script" && src) {
                            jsLibs.push(src);
                        }
                    }
                }
            }
            console.debug(
                `[assets] getBundle(${bundleName}): is_esm=${esmSpecifiers !== null}, ` +
                `${cssLibs.length} CSS, ${jsLibs.length} JS` +
                (esmSpecifiers ? `, ${esmSpecifiers.length} ESM specifiers` : ""),
            );
            return { cssLibs, jsLibs, esmSpecifiers };
        })().catch((reason) => {
            cacheMap.delete(bundleName);
            throw new AssetsLoadingError(`The loading of ${url} failed`, {
                cause: reason,
            });
        });
        cacheMap.set(bundleName, promise);
        return promise;
    },

    /**
     * Loads the given js/css libraries and asset bundles. Note that no library or
     * asset will be loaded if it was already done before.
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
        const { cssLibs, jsLibs, esmSpecifiers } = await getBundle(bundleName);
        console.debug(
            `[assets] loadBundle(${bundleName}): css=${css}, js=${js}, ` +
            `cssLibs=${cssLibs?.length}, jsLibs=${jsLibs?.length}, ` +
            `esmSpecifiers=${esmSpecifiers?.length ?? "null"}`,
        );
        const promises = [];
        if (css && cssLibs) {
            promises.push(
                ...cssLibs.map((url) => assets.loadCSS(url, { targetDoc })),
            );
        }
        if (js && esmSpecifiers) {
            // ESM bundle: use dynamic import() which respects the
            // page's import map for specifier resolution.
            console.debug(
                `[assets] loadBundle(${bundleName}): loading ${esmSpecifiers.length} ESM specifiers via dynamic import()`,
            );
            promises.push(assets.loadESMBundle(esmSpecifiers));
        }
        // Also load non-ESM files (XML template bundles, legacy JS)
        // via the classic path — these are still needed alongside ESM.
        if (js && jsLibs && jsLibs.length) {
            promises.push(
                ...jsLibs.map((url) => assets.loadJS(url, { targetDoc })),
            );
        }
        return Promise.all(promises);
    },

    /**
     * Loads native ESM modules via dynamic import() and registers them
     * in the legacy loader for require() compatibility.
     *
     * @param {string[]} specifiers module specifiers to import
     * @returns {Promise<void>}
     */
    async loadESMBundle(specifiers) {
        const t0 = performance.now();
        const results = await Promise.all(
            specifiers.map(async (specifier) => {
                const mod = await import(specifier);
                return [specifier, mod];
            }),
        );
        const modules = Object.fromEntries(results);
        // Register in legacy loader so require() and odoo.define()
        // dependencies can access these lazy-loaded modules.
        if (globalThis.odoo?.loader?.registerNativeModules) {
            odoo.loader.registerNativeModules(modules);
        }
        console.debug(
            `[assets] loadESMBundle: imported ${specifiers.length} modules in ${(performance.now() - t0).toFixed(1)}ms`,
        );
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
            return cacheMap.get(url);
        }
        const linkEl = targetDoc.createElement("link");
        linkEl.setAttribute("href", url);
        linkEl.type = "text/css";
        linkEl.rel = "stylesheet";
        const promise = new Promise((resolve, reject) =>
            onLoadAndError(linkEl, resolve, async (error) => {
                cacheMap.delete(url);
                if (retryCount < assets.retries.count) {
                    const delay =
                        assets.retries.delay + assets.retries.extraDelay * retryCount;
                    await new Promise((res) => browser.setTimeout(res, delay));
                    linkEl.remove();
                    loadCSS(url, { retryCount: retryCount + 1, targetDoc })
                        .then(resolve)
                        .catch((reason) => {
                            cacheMap.delete(url);
                            reject(reason);
                        });
                } else {
                    reject(
                        new AssetsLoadingError(`The loading of ${url} failed`, {
                            cause: error,
                        }),
                    );
                }
            }),
        );
        cacheMap.set(url, promise);
        targetDoc.head.appendChild(linkEl);
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
            return cacheMap.get(url);
        }
        const scriptEl = targetDoc.createElement("script");
        scriptEl.setAttribute("src", url);
        scriptEl.type = url.includes("web/static/lib/pdfjs/")
            ? "module"
            : "text/javascript";
        const promise = new Promise((resolve, reject) =>
            onLoadAndError(scriptEl, resolve, (error) => {
                cacheMap.delete(url);
                reject(
                    new AssetsLoadingError(`The loading of ${url} failed`, {
                        cause: error,
                    }),
                );
            }),
        );
        cacheMap.set(url, promise);
        targetDoc.head.appendChild(scriptEl);
        return promise;
    },
};
