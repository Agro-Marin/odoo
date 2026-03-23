// @ts-check
/** @odoo-module native */

/** @module @web/core/assets - Lazy-loads CSS/JS asset bundles into documents with caching */

import { Component, onWillStart, whenReady, xml } from "@odoo/owl";
import { session } from "@web/session";

import { registry } from "./registry.js";

/**
 * @typedef {{
 *  cssLibs: string[];
 *  jsLibs: string[];
 *  importMaps: object[];
 *  inlineScripts: object[];
 *  moduleScripts: object[];
 * }} BundleDescriptor
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
 * @returns {Promise<BundleDescriptor>}
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
     * @returns {Promise<BundleDescriptor>}
     */
    getBundle(bundleName) {
        const cacheMap = getGlobalBundleCache();
        if (cacheMap.has(bundleName)) {
            return cacheMap.get(bundleName);
        }
        const url = new URL(`/web/bundle/${bundleName}`, location.origin);
        for (const [key, value] of Object.entries(session.bundle_params || {})) {
            url.searchParams.set(key, value);
        }
        const promise = fetch(url)
            .then(async (response) => {
                const cssLibs = [];
                const jsLibs = [];
                const importMaps = [];
                const inlineScripts = [];
                const moduleScripts = [];
                if (!response.bodyUsed) {
                    for (const node of await response.json()) {
                        const { tag, src, href, type, text } = node;
                        if (tag === "link" && type === "importmap") {
                            // skip — importmap is in script nodes
                        } else if (tag === "link" && href) {
                            if (node.rel === "modulepreload") {
                                // modulepreload hints: skip during lazy load
                            } else {
                                cssLibs.push(href);
                            }
                        } else if (tag === "script" && type === "importmap") {
                            importMaps.push(node);
                        } else if (tag === "script" && type === "module") {
                            moduleScripts.push(node);
                        } else if (tag === "script" && text && !src) {
                            inlineScripts.push(node);
                        } else if (tag === "script" && src) {
                            jsLibs.push(src);
                        }
                    }
                }
                return { cssLibs, jsLibs, importMaps, inlineScripts, moduleScripts };
            })
            .catch((reason) => {
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
     * Handles native ESM bundles: injects import maps before regular scripts,
     * then loads JS, then injects module scripts last (correct execution order).
     *
     * @param {string} bundleName
     * @param {Object} options
     * @param {Document} [options.targetDoc=document] document to which the bundle will be applied (e.g. iframe document)
     * @param {Boolean} [options.css=true] apply bundle css on targetDoc
     * @param {Boolean} [options.js=true] apply bundle js on targetDoc
     * @returns {Promise<void[]>}
     */
    loadBundle(bundleName, { targetDoc = document, css = true, js = true } = {}) {
        if (typeof bundleName !== "string") {
            throw new Error(
                `loadBundle(bundleName:string) accepts only bundleName argument as a string ! Not ${JSON.stringify(
                    bundleName,
                )} as ${typeof bundleName}`,
            );
        }
        return getBundle(bundleName).then(
            ({ cssLibs, jsLibs, importMaps, inlineScripts, moduleScripts }) => {
                const promises = [];



                if (css && cssLibs) {
                    promises.push(
                        ...cssLibs.map((url) => assets.loadCSS(url, { targetDoc })),
                    );
                }

                if (js) {
                    // 1. Import maps MUST be injected before any module scripts
                    for (const node of importMaps) {
                        const el = targetDoc.createElement("script");
                        el.type = "importmap";
                        el.textContent = node.text;
                        targetDoc.head.appendChild(el);
                    }

                    // 2. Inline scripts (e.g. __native_module_names__)
                    for (const node of inlineScripts) {
                        const el = targetDoc.createElement("script");
                        el.textContent = node.text;
                        targetDoc.head.appendChild(el);
                    }

                    // 3. Regular scripts (legacy bundle)
                    promises.push(
                        ...jsLibs.map((url) => assets.loadJS(url, { targetDoc })),
                    );

                    // 4. Module scripts (bridge/esbuild bundle) — must come
                    //    after the legacy bundle loads so __legacyReady resolves.
                    //    We wait for the __nativeReady callback instead of the
                    //    `load` event because module scripts with top-level await
                    //    fire `load` at the first await, not after completion.
                    if (moduleScripts.length) {
                        const jsPromise = Promise.all(
                            jsLibs.map((url) => assets.loadJS(url, { targetDoc })),
                        );
                        const nativeReady = new Promise((resolve) => {
                            ((odoo.__nativeReady ??= {})[bundleName] = resolve);
                        });
                        promises.push(
                            jsPromise.then(() => {
                                console.log(`[loadBundle] ${bundleName}: JS done, yielding for import map`);
                                // Yield a microtask so Chrome's MutationObserver
                                // processes the import map we just injected before
                                // we append the module script that depends on it.
                                return new Promise((r) => setTimeout(r, 0));
                            }).then(() => {
                                const maps = targetDoc.querySelectorAll('script[type="importmap"]');
                                console.log(`[loadBundle] ${bundleName}: ${maps.length} import maps in DOM`);
                                try {
                                    const lastMap = JSON.parse(maps[maps.length - 1]?.textContent || '{}');
                                    const keys = Object.keys(lastMap.imports || {});
                                    console.log(`[loadBundle] ${bundleName}: last import map has ${keys.length} entries: ${keys.slice(0, 5).join(', ')}...`);
                                } catch {}
                                console.log(`[loadBundle] ${bundleName}: injecting module scripts`);
                                for (const node of moduleScripts) {
                                    const el = targetDoc.createElement("script");
                                    el.type = "module";
                                    if (node.src) {
                                        el.src = node.src;
                                    } else if (node.text) {
                                        el.textContent = node.text;
                                    }
                                    el.addEventListener("error", (e) => {
                                        console.error(`[loadBundle] ${bundleName}: MODULE SCRIPT ERROR`, e);
                                    });
                                    el.addEventListener("load", () => {
                                        console.log(`[loadBundle] ${bundleName}: module script load event fired`);
                                    });
                                    targetDoc.head.appendChild(el);
                                }
                                console.log(`[loadBundle] ${bundleName}: waiting for __nativeReady`);
                                return nativeReady;
                            }).then(() => console.log(`[loadBundle] ${bundleName}: DONE`)),
                        );
                    }
                }

                return Promise.all(promises);
            },
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
                    await new Promise((res) => setTimeout(res, delay));
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
