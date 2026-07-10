// @ts-check
/** @odoo-module native */

/** @module @web/core/module_bridge - Build runtime re-export bridge modules from odoo.loader.modules */

/**
 * Canonical JS-side builder for "bridge" modules: tiny ES modules that
 * re-export a specifier's namespace from the live ``odoo.loader.modules``
 * map, preserving singleton identity when a bundle loads into a foreign
 * document (iframe) whose bare imports must resolve to already-evaluated
 * instances.
 *
 * RUNTIME counterpart of the BUILD-TIME generator ``_bridge_shim_source``
 * in ``odoo/tools/assets/esm_graph.py`` — the two MUST emit the same shape
 * so server-built and client-built bridges are interchangeable
 * (``@web/core/assets.loadESMBundle`` reuses server bridges where they
 * exist, falling back to runtime ``data:`` bridges otherwise). Keep in
 * sync with the Python generator.
 */

// Identifier names that can appear as ``export const <name>``.  Non-identifier
// keys (none in practice for ESM namespaces, but guarded) are skipped.
const VALID_EXPORT_NAME = /^[a-zA-Z_$][\w$]*$/;

/**
 * Build the ES-module source of a bridge re-exporting ``specifier`` from
 * ``odoo.loader.modules``.  Field-for-field mirror of Python
 * ``_bridge_shim_source``:
 *
 *   const _m = odoo.loader.modules.get("<specifier>");
 *   const _d = _m?.default ?? _m;
 *   export default _d;
 *   export const <name> = _m?.<name>;   // one per named export
 *
 * @param {string} specifier  module specifier, e.g. ``@web/core/registry``
 * @param {Iterable<string>} exportNames  candidate named exports (``default``
 *   and non-identifier names are filtered out)
 * @returns {string} ES-module source
 */
export function buildBridgeModuleSource(specifier, exportNames) {
    const lines = [
        `const _m = odoo.loader.modules.get(${JSON.stringify(specifier)});`,
        `const _d = _m?.default ?? _m;`,
        `export default _d;`,
    ];
    for (const name of exportNames) {
        if (name !== "default" && VALID_EXPORT_NAME.test(name)) {
            lines.push(`export const ${name} = _m?.${name};`);
        }
    }
    return lines.join("\n");
}

/**
 * Wrap bridge-module source as a ``data:text/javascript`` URI for use as an
 * import-map value.
 *
 * @param {string} source
 * @returns {string}
 */
export function toDataModuleUrl(source) {
    return `data:text/javascript,${encodeURIComponent(source)}`;
}

/**
 * Conventional mapping from a bare ``@addon/rest`` specifier to the URL
 * esbuild would have fetched for it individually
 * (``@<addon>/<rest>`` → ``/<addon>/static/src/<rest>.js``).  Lets a caller
 * also intercept *relative* imports that resolve to that URL, so a bridged
 * module is never re-evaluated outside its original bundle (which would split
 * the registry singleton).
 *
 * @param {string} specifier
 * @returns {string | null} the conventional URL, or ``null`` if the specifier
 *   doesn't map (not ``@``-scoped, contains ``..``, or has no ``/``).
 */
export function specToModuleUrl(specifier) {
    if (!specifier.startsWith("@") || specifier.includes("..")) {
        return null;
    }
    const slash = specifier.indexOf("/");
    if (slash <= 1) {
        return null;
    }
    const addon = specifier.slice(1, slash);
    const rest = specifier.slice(slash + 1);
    return `/${addon}/static/src/${rest}.js`;
}

/**
 * Whether an import-map value re-exports from ``odoo.loader.modules`` (a
 * ``data:`` runtime bridge or a server bridge attachment) rather than being a
 * raw source file.  Only such targets are safe to reuse for relative-import
 * interception — pointing a relative URL at a raw source file would
 * re-evaluate the module and split the registry singleton.
 *
 * @param {unknown} url
 * @returns {boolean}
 */
export function isLoaderBridgeUrl(url) {
    return (
        typeof url === "string" &&
        (url.startsWith("data:") || url.includes("/web/assets/esm/bridges/"))
    );
}
