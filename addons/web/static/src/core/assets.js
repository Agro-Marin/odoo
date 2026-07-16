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
// Per-document cache of cross-document ESM bundle loads, keyed by the specifier
// signature. Dedups repeated ``loadESMBundle`` calls into the SAME foreign
// document so import-map keys aren't re-injected and the module graph isn't
// re-imported; a rejected load is evicted so a later call may retry.
// Main-document loads are excluded — deduped upstream via ``getBundle``/
// ``injectedImportMapKeys``, which mutate global state this cache doesn't model.
export const crossDocESMBundleCache = new WeakMap();
// Specifiers already resolvable by the page's *existing* import maps — injected
// by this module or rendered server-side into the initial HTML. Chromium merges
// multi-importmap rules by appending, but a later rule for an already-defined
// spec is dropped with "An import map rule for specifier '<spec>' was removed,
// as it conflicted with an existing rule" — so treat every spec already present
// as off-limits for lazy ``loadBundle`` re-declaration.
const injectedImportMapKeys = new Set();

// Monotonic token for cross-document ``loadESMBundle`` done/error event names.
// Deterministic (vs ``Math.random``), collision-proof across concurrent calls,
// and predictable for tests.
let crossDocLoadSeq = 0;

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
 * @param {() => void} [onPageHideCleanup] invoked when the page hides before
 *  the asset settles (bfcache hazard) — evict cache entries here
 */
const onLoadAndError = (el, onLoad, onError, onPageHideCleanup) => {
    const onLoadListener = (/** @type {Event} */ event) => {
        removeListeners();
        onLoad(event);
    };

    const onErrorListener = (/** @type {Event} */ error) => {
        removeListeners();
        onError(/** @type {any} */ (error));
    };

    // Cleans up the load/error listeners if the page is unloaded before the asset
    // settles. It MUST itself be removed once the asset loads/errors, otherwise
    // every loadJS/loadCSS over a session leaks a permanent `pagehide` listener
    // (and retained closures) on `window`.
    const onPageHide = () => {
        removeListeners();
        // On bfcache restore (Safari back-nav) the JS heap, including the asset
        // cache, comes back intact, but this promise can never settle (listeners
        // gone, request aborted). Evict the cache entry so a post-restore load
        // re-injects instead of returning a dead promise forever.
        onPageHideCleanup?.();
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

// Entries are OWL Component classes — ``LazyComponent`` below resolves the
// registered class via ``registry.category("lazy_components").get(name)`` and
// mounts it via ``<t t-component="Component" .../>``. Validate at ``add()`` time
// so a non-Component entry surfaces here instead of failing deep inside OWL at
// mount with an unhelpful error (same pattern as the ``dialogs`` registry, see
// ``ui/dialog/dialog_service.js``).
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
        // The promise is stored in the cache synchronously (before it resolves)
        // so concurrent calls for the same bundle share a single fetch.
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
            // Inject the bundle's import map entries before the dynamic imports.
            // Required when specifiers aren't already pre-registered in the page's
            // main import map (e.g. ``loadBundle("web.assets_emoji")`` from the
            // unit-test page, whose setup bundle only pre-registers
            // ``web.assets_web``'s specifiers). Browsers support multiple
            // ``<script type="importmap">`` tags per document, merging maps as
            // long as no conflicting keys redefine an entry.
            if (importMap) {
                // Re-seed in case another async flow appended an import map between
                // whenReady and this call. Idempotent and cheap vs. the injection it
                // prevents.
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
                    // The specifier may already be import-mapped to another
                    // module (first injection wins for the whole session, e.g.
                    // a test stub claimed it first). Delegating shims expose
                    // ``__setImplUrl`` so a later load of the same bundle can
                    // still route them to this bundle's actual module.
                    const mappedUrl = importMap?.[specifier];
                    if (mappedUrl && typeof mod.__setImplUrl === "function") {
                        // Absolutize: the shim may live in a data: module,
                        // where path-relative imports cannot be resolved.
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
        // Cross-document dedup: a repeated load of the same specifier set into the
        // same foreign document must NOT re-inject import-map keys nor re-import
        // the graph. Everything to the terminal ``new Promise`` below runs
        // synchronously, so the cache entry is installed before any concurrent
        // caller can observe a miss.
        const cacheKey = JSON.stringify(specifiers);
        if (!crossDocESMBundleCache.has(targetDoc)) {
            crossDocESMBundleCache.set(targetDoc, new Map());
        }
        const bundleCache = crossDocESMBundleCache.get(targetDoc);
        if (bundleCache.has(cacheKey)) {
            log("loadESMBundle:crossDoc cache-hit", "specs=", specifiers.length);
            return bundleCache.get(cacheKey);
        }
        // Cross-document: run the imports inside targetDoc so they use its import
        // map and register into its own odoo.loader. Build an extra import map
        // combining bridge entries for every module already registered in the
        // target's odoo.loader — so transitive ``@web/*`` imports resolve to
        // data: URIs re-exporting the SAME instance instead of re-evaluating and
        // splitting the registry singleton — with the bundle-specific import map
        // from the caller. Reuse the server-provided map's bridges where a
        // specifier is already covered, synthesising a runtime ``data:`` bridge
        // only where the server couldn't statically predict it; bridge sources
        // are built by ``@web/core/module_bridge`` in the SAME format as the
        // server-side generator (``esm_graph.py::_bridge_shim_source``). Browsers
        // accept multiple import maps as long as rules don't conflict — rules
        // already present in targetDoc are kept.
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
                // Reuse the server's cacheable bridge if it already provides one for
                // ``spec``, else synthesise a runtime data: bridge. NEVER a raw source
                // file — that would re-evaluate the module and split the singleton.
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
        const settlePromise = new Promise((resolve, reject) => {
            // Done/error are paired listeners on the target window: whichever fires
            // must remove ALL (`{once: true}` alone would leak the others). The
            // script "error" listener covers the injected module never running
            // (e.g. parse failure); ``pagehide`` covers targetDoc being navigated
            // away or torn down before done/error fires — both would otherwise hang
            // the promise forever (mirrors ``onLoadAndError``'s ``pagehide`` cleanup).
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
        // Keep the shared promise in the per-document cache; evict on failure so
        // a later call may retry (a resolved load stays cached — dedup hit).
        bundleCache.set(cacheKey, settlePromise);
        settlePromise.catch(() => bundleCache.delete(cacheKey));
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
        // Cache the WHOLE retry chain up front and keep it cached until the chain
        // settles. The previous code deleted the entry inside each error handler
        // and only re-populated it after the backoff, leaving a window where a
        // concurrent ``loadCSS(url)`` missed the cache and started an independent
        // parallel retry chain (duplicate <link>s). A single ``attempt`` recursion
        // that never touches the cache closes that window.
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
                        // Content-addressed bundle URLs (``/web/assets/...``)
                        // can never succeed by re-requesting the same URL — a
                        // 404 means the attachment was GC-swept and only a
                        // page reload (see the loader shim's
                        // ``handleAssetLoadError``) mints a fresh URL. Retry
                        // only external/plain URLs, where transient failures
                        // are plausible.
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
                    () => cacheMap.delete(url),
                ),
            );
            targetDoc.head.appendChild(linkEl);
            return attemptPromise;
        };
        const promise = /** @type {Promise<void>} */ (
            runAttempt(retryCount).catch((reason) => {
                // Terminal failure: evict so a future caller can retry fresh.
                cacheMap.delete(url);
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
        // Dynamically-inserted scripts default to async=true, i.e. they execute
        // in COMPLETION order. Classic multi-file bundles rely on insertion
        // order (e.g. web.ace_lib mode files calling `ace.define` must run
        // after ace.js), so opt back into ordered execution.
        scriptEl.async = false;
        const promise = new Promise((resolve, reject) =>
            onLoadAndError(
                scriptEl,
                resolve,
                (error) => {
                    cacheMap.delete(url);
                    reject(
                        new AssetsLoadingError(`The loading of ${url} failed`, {
                            cause: error,
                        }),
                    );
                },
                () => {
                    if (cacheMap.get(url) === promise) {
                        cacheMap.delete(url);
                    }
                },
            ),
        );
        cacheMap.set(url, promise);
        targetDoc.head.appendChild(scriptEl);
        return promise;
    },
};
