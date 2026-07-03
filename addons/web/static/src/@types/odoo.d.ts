/**
 * Ambient declarations for the post-ESM Odoo module loader shim.
 *
 * Keep in sync with ``web/static/src/module_loader.js``.  The shim
 * publishes ``globalThis.odoo`` before any ES module evaluates; these
 * types describe the shape consumers can rely on.
 */

class OdooModuleLoader {
    /**
     * Module-graph lifecycle event surface.  Dispatches a single
     * event today:
     *
     *   • ``rebind`` — a ``CustomEvent<OdooModuleRebindDetail>`` fired
     *     when ``registerNativeModules`` re-binds an already-known
     *     specifier to a DIFFERENT namespace object (duplicated module
     *     in the bundle graph in production; an expected re-evaluation
     *     in dev hot-reload).
     *
     * Subscribe via ``odoo.loader.bus.addEventListener("rebind", ...)``.
     */
    bus: EventTarget;

    /**
     * Shared Map of module specifier → module namespace.  Populated
     * by ``registerNativeModules`` from the esbuild bundle's
     * auto-generated entry.  Sibling bundles resolve to the SAME
     * entries via ``data:`` URI bridges so registry singletons stay
     * coherent across bundle boundaries.
     */
    modules: Map<string, OdooModule>;

    constructor();

    /**
     * Register already-evaluated ES module namespaces into
     * ``modules`` (last-write-wins).  Called from the esbuild bundle's
     * entry point and from ``@web/core/assets.loadESMBundle`` cross-doc
     * mode.  Re-binding a specifier to a different namespace object
     * emits ``rebind`` on ``bus``.
     */
    registerNativeModules(modulesByName: Record<string, OdooModule>): void;

    /**
     * Self-heal a failed bundle-asset script load (GC'd content-addressed
     * URL on a stale cached page) with ONE rate-limited page reload.
     * Returns whether a reload was triggered.
     */
    handleAssetLoadError(target: EventTarget | null): boolean;

    /** Reload seam — overridden in tests; reloads only THIS document. */
    _reloadPage(): void;
}

type OdooModule = Record<string, any>;

/** ``detail`` payload of the ``rebind`` event on ``OdooModuleLoader.bus``. */
interface OdooModuleRebindDetail {
    /** Specifiers whose namespace object changed in this registration. */
    specifiers: string[];
}

declare const odoo: {
    csrf_token: string;
    debug: string;
    loader: OdooModuleLoader;
    translationContext?: string;
    /**
     * Server info, available after session initialization.
     *
     * Field names mirror the runtime keys written by
     * ``boot/start.js:startWebClient``, which forwards them straight from
     * ``session.*`` (snake_case from Python).  The earlier camelCase
     * declaration (``serverVersion`` / ``serverVersionInfo``) advertised
     * keys that were never written at runtime — verified zero JS readers
     * of either form, but the type contract should reflect what's
     * actually there.
     */
    info?: {
        db: string;
        server_version: string;
        server_version_info: [number, number, number, string, number];
        isEnterprise: boolean;
        [key: string]: any;
    };
};

// NOTE: luxon is a real ES module resolved via the import map
// (``odoo.libs.constants.ODOO_EXTERNAL_LIBS``); consumers import it from
// ``@web/core/l10n/luxon`` (typed re-export surface).  There is no
// ``window.luxon`` global any more — the old UMD IIFE + ``declare var
// luxon`` ambient global were removed with the ESM migration.
