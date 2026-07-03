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

const log = makeAssetLog("js");

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
// Track specifiers that are resolvable by the page's *existing* import
// maps — whether injected by this module or rendered server-side into
// the initial HTML.  Chromium's multi-importmap support merges maps by
// appending rules, but a later rule for a spec already defined earlier
// is dropped with "An import map rule for specifier '<spec>' was
// removed, as it conflicted with an existing rule".  Treat every spec
// already present in the document as off-limits so lazy ``loadBundle``
// calls don't re-declare them.
const injectedImportMapKeys = new Set();

// Monotonic token for cross-document ``loadESMBundle`` done/error event names.
// Deterministic (vs ``Math.random``), collision-proof across concurrent calls,
// and predictable for tests.
let crossDocLoadSeq = 0;

/**
 * Pre-seed ``injectedImportMapKeys`` from the document's existing
 * ``<script type="importmap">`` tags.  The initial page import map is
 * rendered server-side (``ir_qweb._get_esm_asset_nodes``) and already
 * contains every specifier of the dynamic child bundles of
 * ``web.assets_web`` — tour, spreadsheet, html_editor, mail, etc.
 * Without this seed, the first ``loadBundle("web_tour.interactive")``
 * call after page load would re-inject those same specifiers and
 * Chromium would log a warning for each one.
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
        // The `[src]` selector guarantees the attribute is present.
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
 */
const onLoadAndError = (el, onLoad, onError) => {
    const onLoadListener = (/** @type {Event} */ event) => {
        removeListeners();
        onLoad(event);
    };

    const onErrorListener = (/** @type {Event} */ error) => {
        removeListeners();
        onError(/** @type {any} */ (error));
    };

    // Cleans up the load/error listeners if the page is unloaded before the
    // asset settles. It MUST itself be removed once the asset loads/errors,
    // otherwise every loadJS/loadCSS over a session leaves a permanent
    // `pagehide` listener (and retained closures) on `window` -- an unbounded
    // leak for long-lived sessions that lazy-load many bundles.
    const onPageHide = () => {
        removeListeners();
    };

    const removeListeners = () => {
        el.removeEventListener("load", onLoadListener);
        el.removeEventListener("error", onErrorListener);
        window.removeEventListener("pagehide", onPageHide);
    };

    el.addEventListener("load", onLoadListener);
    el.addEventListener("error", onErrorListener);
    window.addEventListener("pagehide", onPageHide);
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

// Entries are OWL Component classes — ``LazyComponent`` below resolves
// the registered class via ``registry.category("lazy_components").get(name)``
// and mounts it via ``<t t-component="Component" .../>``.  A non-Component
// entry would fail at mount time deep inside OWL with an unhelpful error;
// catching the misregistration at ``add()`` time surfaces the bug at the
// point of registration instead.  Follows the same pattern as the
// ``dialogs`` registry (see ``ui/dialog/dialog_service.js:13``).
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
            log("getBundle:cache-hit", bundleName);
            return /** @type {Promise<BundleFileNames>} */ (cacheMap.get(bundleName));
        }
        log("getBundle:fetch", bundleName);
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
            cacheMap.delete(bundleName);
            log("getBundle:error", bundleName, reason);
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
            promises.push(...jsLibs.map((url) => assets.loadJS(url, { targetDoc })));
        }
        const result = await Promise.all(promises);
        log("loadBundle:done", bundleName, "promises=", promises.length);
        return result;
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
            // Inject the bundle's import map entries before kicking off
            // the dynamic imports.  Required when this bundle's
            // specifiers aren't already pre-registered in the page's
            // main import map (e.g. ``loadBundle("web.assets_emoji")``
            // from the unit-test page, where the setup bundle doesn't
            // pre-register dynamic-child specifiers — only
            // ``web.assets_web`` does).  Modern browsers support
            // multiple ``<script type="importmap">`` tags per
            // document; later maps are merged with earlier ones as
            // long as no conflicting keys redefine an entry.
            if (importMap) {
                // Re-seed in case another async flow appended an
                // import map between whenReady and this call.  Idempotent
                // and O(#existing-specs); cheap compared to the injection
                // it prevents.
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
        // Cross-document: run the imports inside targetDoc so they use
        // its import map and register into its own odoo.loader.  Build
        // an extra import map for the target document that combines:
        //   - bridge entries for every module already registered in the
        //     target's odoo.loader (so transitive ``@web/*`` imports
        //     resolve to data: URIs re-exporting from odoo.loader); and
        //   - the bundle-specific import map provided by the caller.
        // Browsers accept multiple import maps as long as rules don't
        // conflict — rules already present in targetDoc are kept.
        const targetWin = /** @type {any} */ (targetDoc.defaultView);
        // Build an extra import map for the target document.  For every module
        // already registered in the target's odoo.loader, resolve its bare
        // specifier (and the conventional file URL that a relative import
        // would hit) to a bridge that re-exports the SAME instance from
        // odoo.loader — so transitive ``@web/*`` imports don't re-evaluate and
        // split the registry singleton.  Reuse the server-provided bundle
        // import map (real URLs + cacheable bridge attachments) wherever it
        // already covers a specifier, synthesising a runtime ``data:`` bridge
        // only for modules the server could not statically predict.  Bridge
        // sources are built by ``@web/core/module_bridge`` in the SAME format
        // as the server-side generator (``esm_graph.py::_bridge_shim_source``).
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
                // A target that re-exports ``spec`` from odoo.loader: reuse the
                // server's cacheable bridge when it already provides one,
                // otherwise synthesise a runtime data: bridge.  NEVER a raw
                // source file — pointing the relative-import URL at the source
                // would re-evaluate the module and split the singleton.
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
        // Server-provided entries (real URLs + targeted bridges) win for any
        // overlapping keys.
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
        const token = ++crossDocLoadSeq;
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
        await new Promise((resolve, reject) => {
            // Done/error are paired listeners on the target window: whichever
            // fires must remove BOTH (a `{once: true}` pair only removes the
            // one that fired, leaking the other). The script element "error"
            // listener covers the case where the injected module never runs
            // (e.g. parse failure) — without it the promise hangs forever.
            const settle = (/** @type {() => void} */ fn) => {
                win.removeEventListener(doneEvent, onDone);
                win.removeEventListener(errorEvent, onError);
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
            win.addEventListener(doneEvent, onDone);
            win.addEventListener(errorEvent, onError);
            scriptEl.addEventListener("error", onScriptError);
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
            return /** @type {Promise<void>} */ (cacheMap.get(url));
        }
        if (retryCount === 0) {
            log("loadCSS", url);
        } else {
            log("loadCSS:retry", url, "attempt=", retryCount);
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
            return /** @type {Promise<void>} */ (cacheMap.get(url));
        }
        log("loadJS", url);
        const scriptEl = targetDoc.createElement("script");
        scriptEl.setAttribute("src", url);
        scriptEl.type = "text/javascript";
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
