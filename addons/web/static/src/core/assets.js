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
 *  esmImportMap: Record<string, string> | null;
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
            let esmImportMap = null;
            if (!response.bodyUsed) {
                const result = await response.json();
                if (result.is_esm) {
                    // ESM bundle: native modules are loaded via import().
                    // Skip .esm.js files (esbuild output) — they have
                    // import statements that fail as regular <script>.
                    // Keep .min.js (UMD libs like Bootstrap).
                    esmSpecifiers = result.specifiers || [];
                    esmImportMap = result.import_map || null;
                    // Include ESM template URL so templates self-register
                    // via registerTemplate() when imported.
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
                        } else if (type === "script" && src) {
                            jsLibs.push(src);
                        }
                    }
                }
            }
            return { cssLibs, jsLibs, esmSpecifiers, esmImportMap };
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
        const { cssLibs, jsLibs, esmSpecifiers, esmImportMap } = await getBundle(bundleName);
        const promises = [];
        if (css && cssLibs) {
            promises.push(
                ...cssLibs.map((url) => assets.loadCSS(url, { targetDoc })),
            );
        }
        if (js && esmSpecifiers) {
            // ESM bundle: use dynamic import() which respects the
            // page's import map for specifier resolution.
            promises.push(
                assets.loadESMBundle(esmSpecifiers, {
                    targetDoc,
                    importMap: esmImportMap,
                }),
            );
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
     * in the target document's ``odoo.loader.modules`` for runtime access
     * by dynamic callers.
     *
     * When ``targetDoc`` is a foreign document (e.g. an iframe), the
     * imports MUST run in that document's context so specifiers resolve
     * via its import map and modules land in its ``odoo.loader`` — not
     * the parent's.  Achieved by injecting a ``<script type="module">``
     * into ``targetDoc`` that performs the dynamic imports in-context.
     *
     * @param {string[]} specifiers module specifiers to import
     * @param {{ targetDoc?: Document, importMap?: Record<string, string> | null }} [options]
     * @returns {Promise<void>}
     */
    async loadESMBundle(specifiers, { targetDoc = document, importMap = null } = {}) {
        if (targetDoc === document || targetDoc.defaultView === window) {
            const results = await Promise.all(
                specifiers.map(async (specifier) => {
                    const mod = await import(specifier);
                    return [specifier, mod];
                }),
            );
            const modules = Object.fromEntries(results);
            if (globalThis.odoo?.loader?.registerNativeModules) {
                odoo.loader.registerNativeModules(modules);
            }
            return;
        }
        // Cross-document: run the imports inside targetDoc so they use
        // its import map and register into its own odoo.loader.  Build
        // an extra import map for the target document that combines:
        //   - bridge entries for every module already registered in the
        //     target's odoo.loader (so transitive ``@web/*`` imports
        //     resolve to data: URIs re-exporting from odoo.loader); and
        //   - the bundle-specific import map provided by the caller.
        // Browsers accept multiple import maps as long as rules don't
        // conflict — rules already present in targetDoc are kept.
        const targetWin = targetDoc.defaultView;
        const extraMap = {};
        const loadedModules = targetWin.odoo?.loader?.modules;
        const validName = /^[a-zA-Z_$][\w$]*$/;
        // Conventional mapping from bare specifier to the URL esbuild
        // would have fetched if the module had been loaded individually:
        // ``@<addon>/<rest>`` → ``/<addon>/static/src/<rest>.js``.  Lets us
        // also intercept *relative* imports (``./animation.js``) that
        // resolve to the same URL, so the module is never re-evaluated
        // outside its original esbuild bundle (which would trigger
        // duplicate registry errors).
        const specToUrl = (spec) => {
            if (!spec.startsWith("@") || spec.includes("..")) {
                return null;
            }
            const slash = spec.indexOf("/");
            if (slash <= 1) {
                return null;
            }
            const addon = spec.slice(1, slash);
            const rest = spec.slice(slash + 1);
            return `/${addon}/static/src/${rest}.js`;
        };
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
                const names = Object.keys(mod).filter(
                    (k) => validName.test(k) && k !== "default",
                );
                const nameLines = names
                    .map(
                        (n) =>
                            `export const ${n} = _m[${JSON.stringify(n)}];`,
                    )
                    .join("\n");
                const shim =
                    `const _m = window.odoo.loader.modules.get(${JSON.stringify(spec)});\n` +
                    `export default _m?.default ?? _m;\n` +
                    nameLines;
                const dataUri = `data:text/javascript,${encodeURIComponent(shim)}`;
                extraMap[spec] = dataUri;
                const url = specToUrl(spec);
                if (url) {
                    extraMap[url] = dataUri;
                }
            }
        }
        if (importMap) {
            // Bundle-specific entries (real URLs + targeted bridges)
            // override the generic shims above for any overlapping keys.
            Object.assign(extraMap, importMap);
        }
        if (Object.keys(extraMap).length) {
            const mapEl = targetDoc.createElement("script");
            mapEl.type = "importmap";
            mapEl.textContent = JSON.stringify({ imports: extraMap });
            (targetDoc.head || targetDoc.documentElement).appendChild(mapEl);
        }
        const doneEvent = `__odoo_esm_bundle_loaded_${Math.random().toString(36).slice(2)}`;
        const errorEvent = `__odoo_esm_bundle_error_${Math.random().toString(36).slice(2)}`;
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
        const win = targetDoc.defaultView;
        await new Promise((resolve, reject) => {
            win.addEventListener(doneEvent, () => resolve(), { once: true });
            win.addEventListener(
                errorEvent,
                (e) => reject(e.detail || new Error(`loadESMBundle failed`)),
                { once: true },
            );
            (targetDoc.head || targetDoc.documentElement).appendChild(scriptEl);
        });
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
