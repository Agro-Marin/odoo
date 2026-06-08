/**
 * Ambient declarations for the post-ESM Odoo module loader shim.
 *
 * Keep in sync with ``web/static/src/module_loader.js``.  The shim
 * publishes ``globalThis.odoo`` before any ES module evaluates; these
 * types describe the shape consumers can rely on.
 */

class OdooModuleLoader {
    /**
     * Free extension point — no standard event names are dispatched
     * by the loader itself today.  Third-party integrations can
     * subscribe for future native-module lifecycle hooks.
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
     * ``modules``.  Called from the esbuild bundle's entry point and
     * from ``@web/core/assets.loadESMBundle`` cross-doc mode.
     */
    registerNativeModules: (modulesByName: Record<string, OdooModule>) => void;
}

type OdooModule = Record<string, any>;

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

/**
 * Luxon datetime library. Loaded via a non-deferred <script> tag before
 * the ESM bundle evaluates (see `ir_qweb._get_native_module_nodes`); the
 * IIFE assigns `window.luxon` (and therefore `globalThis.luxon`) as a
 * side-effect. `declare var` (not `const`) is required for the binding
 * to land on the `globalThis` interface so that `globalThis.luxon` and
 * bare `luxon` references both type-check. Declared loose because we
 * don't ship Luxon's full .d.ts surface here — consumers that need
 * precise types should destructure DateTime/Duration/Settings and rely
 * on the destructured locals.
 */
declare var luxon: any;
