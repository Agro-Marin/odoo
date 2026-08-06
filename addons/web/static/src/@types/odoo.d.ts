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

    /**
     * Beacon seam — the shim's error-reporting internals, exposed for tests.
     *
     * These live in the shim's IIFE closure and the pre-ESM shim cannot
     * ``export``, so a test has no other way to reach them. ``serializeCause``
     * and ``hashCode`` are byte-identical copies of the helpers in
     * ``@web/core/errors/error_beacon``; keep all three in step.
     */
    _beacon: {
        reportError(payload: Record<string, any>): void;
        seenErrors: Set<string>;
        serializeCause(cause: unknown): string;
        hashCode(str: string): string;
    };
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
     * Whether the web client has finished mounting.
     *
     * Written by ``boot/start.js:startWebClient`` — ``false`` before the mount,
     * ``true`` once the app is up — and read by every beacon emitter to decide
     * `pre_boot` vs `post_boot`, and by ``module_loader.js`` to stand down its
     * pre-boot error listener once the error service owns reporting.
     *
     * Undeclared until now, which is why both writers cast through
     * ``/** @type {any} *\/`` and every reader through an inline cast: the
     * property has always existed, only the contract was missing.
     */
    isReady?: boolean;
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
