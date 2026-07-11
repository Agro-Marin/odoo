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
 *
 * CONTRACT — bridged modules must not rely on mutable ``export let``
 * bindings: a bridge re-exports ``export const <name> = _m?.<name>`` — a
 * VALUE SNAPSHOT taken when the bridge evaluates.  ES-module live bindings
 * cannot be reproduced by a generated module (only ``export ... from``
 * preserves liveness, and a ``data:`` bridge has no source URL to re-export
 * from), so a module that reassigns an ``export let`` after load (the
 * lazy-loader pattern) would present a permanently-stale value — typically
 * ``null`` — to every cross-document consumer.  Modules that expose a
 * lazily-loaded value must instead export a STABLE ``const`` whose reads
 * forward to the current value — see {@link makeLazyFacade}, used by
 * ``@web/core/lib/chartjs``, ``@web/core/lib/fullcalendar`` and
 * ``@web/core/utils/pdfjs``.
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
 * Build a stable ``const``-exportable facade over a lazily-loaded value, so
 * the exporting module honours the bridge contract above (no mutable
 * ``export let``): the facade object never changes identity — a bridge's
 * value snapshot of it stays valid — while every interaction (property
 * reads/writes, calls, construction) forwards to the CURRENT value returned
 * by ``getValue()``.
 *
 * Intended for the lazy library loaders (``export const Chart =
 * makeLazyFacade(() => _chart, { constructable: true })``): consumers keep
 * their existing ``await loadChartJS(); new Chart(...)`` /
 * ``pdfjsLib.getDocument(...)`` call sites, in the parent document and in
 * bridged (iframe) documents alike.
 *
 * Before the value is loaded, interactions fall back to the bare target
 * (reads yield ``undefined``, construction throws) — consumers must await
 * the loader first, exactly as with the previous ``null`` binding.  Note
 * the facade itself is always truthy: code must gate on the loader
 * promise, not on the binding's truthiness.
 *
 * @param {() => any} getValue returns the currently-loaded value
 *   (``null``/``undefined`` while not yet loaded)
 * @param {{ constructable?: boolean }} [options] pass ``constructable:
 *   true`` when the loaded value is called/constructed (e.g. a class);
 *   leave false for plain namespace objects.
 * @returns {any}
 */
export function makeLazyFacade(getValue, { constructable = false } = {}) {
    const target = constructable ? function () {} : Object.create(null);
    const current = () => getValue() ?? undefined;
    return new Proxy(target, {
        apply(t, thisArg, args) {
            return Reflect.apply(current(), thisArg, args);
        },
        construct(t, args) {
            return Reflect.construct(current(), args);
        },
        get(t, p) {
            const value = current();
            return value === undefined ? Reflect.get(t, p) : Reflect.get(value, p);
        },
        set(t, p, v) {
            const value = current();
            return Reflect.set(value === undefined ? t : value, p, v);
        },
        has(t, p) {
            const value = current();
            return value === undefined ? Reflect.has(t, p) : Reflect.has(value, p);
        },
        deleteProperty(t, p) {
            const value = current();
            return Reflect.deleteProperty(value === undefined ? t : value, p);
        },
        defineProperty(t, p, desc) {
            const value = current();
            return Reflect.defineProperty(value === undefined ? t : value, p, desc);
        },
        ownKeys(t) {
            const value = current();
            if (value === undefined) {
                return Reflect.ownKeys(t);
            }
            // Proxy invariant: the target's non-configurable own keys (a
            // function target's "prototype") must always be reported.
            const keys = new Set(Reflect.ownKeys(value));
            for (const key of Reflect.ownKeys(t)) {
                const desc = Reflect.getOwnPropertyDescriptor(t, key);
                if (desc && !desc.configurable) {
                    keys.add(key);
                }
            }
            return [...keys];
        },
        getOwnPropertyDescriptor(t, p) {
            const value = current();
            const desc =
                value === undefined
                    ? Reflect.getOwnPropertyDescriptor(t, p)
                    : (Reflect.getOwnPropertyDescriptor(value, p) ??
                      Reflect.getOwnPropertyDescriptor(t, p));
            if (!desc) {
                return undefined;
            }
            const targetDesc = Reflect.getOwnPropertyDescriptor(t, p);
            if (!targetDesc || targetDesc.configurable) {
                // Proxy invariant: a property may only be reported
                // non-configurable if the target's own property is.
                desc.configurable = true;
            } else {
                // Non-configurable on the target (function "prototype"):
                // report it non-configurable but writable, since the
                // forwarded value may differ from the target's.
                desc.configurable = false;
                if ("writable" in desc) {
                    desc.writable = true;
                }
            }
            return desc;
        },
    });
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
