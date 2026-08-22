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
     * The JS error beacon. Not a seam and not a copy: this IS the one
     * implementation, because the pre-ESM shim must be able to report an error
     * thrown before any module can be imported, so it cannot import one.
     * ``@web/core/errors/error_beacon`` is a typed facade that calls straight
     * into ``reportJsError`` here — one dedup set, one set of limits, one
     * payload shape, and therefore no parity to keep.
     *
     * ``seenErrors``, ``serializeCause``, ``hashCode`` and ``limits`` are
     * exposed because the shim cannot ``export`` and tests have no other way in.
     */
    _beacon: {
        reportJsError(info: {
            message: unknown;
            kind?: string;
            phase?: string;
            filename?: string;
            line?: number;
            col?: number;
            stack?: string;
            cause?: unknown;
            reloaded?: boolean;
            dedup?: boolean;
        }): boolean;
        seenErrors: Set<string>;
        serializeCause(cause: unknown): string;
        hashCode(str: string): string;
        limits: {
            ENDPOINT: string;
            MAX_MESSAGE: number;
            MAX_STACK: number;
            MAX_CAUSE: number;
            MAX_CAUSE_DEPTH: number;
            MAX_SEEN_KEYS: number;
            KINDS: Set<string>;
        };
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
     * The public Discuss page's initial store payload, injected as a literal by
     * `mail/views/discuss_public_templates.xml` beside `__session_info__` and
     * read once by `mail/…/discuss/core/public/boot.js` to seed `mail.store`.
     *
     * Undeclared until 2026-08-18, so the single line that reads it was a
     * standing TS2339 on a file both default-deny lanes lock at zero — the
     * property has always existed, only the contract was missing.
     */
    discuss_data?: Record<string, any>;
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
        /**
         * Six elements, not five: `odoo/release.py` declares
         * `tuple[int, int, int, str, int, str]` and the last is the EDITION
         * tag — `"e"` for enterprise, `""` otherwise. Declared as a 5-tuple
         * until 2026-08-17, which typed away the very element
         * `publishOdooInfo()` reads to compute `isEnterprise`.
         */
        server_version_info: [number, number, number, string, number, string];
        isEnterprise: boolean;
        [key: string]: any;
    };
};
