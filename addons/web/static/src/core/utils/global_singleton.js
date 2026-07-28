// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/global_singleton - One-per-page state anchored on globalThis, shared across bundle copies */

/**
 * Namespace every anchor lives under, so the whole set is enumerable in
 * DevTools (``__odoo_singletons__``) instead of being scattered across
 * ad-hoc top-level globals.
 */
const NAMESPACE = "__odoo_singletons__";

/**
 * Return the one-per-PAGE instance for ``key``, creating it on first call.
 *
 * A handful of modules must hold exactly one instance no matter how many
 * times their source is evaluated: the registry, the template registry, the
 * RPC bus and in-flight dedup map, the asset caches, the translation state,
 * the ``uniqueId`` counter. Odoo evaluates the same module more than once by
 * design — a lazy child bundle inlines its own copy, and a bundle loaded into
 * an iframe evaluates in that document — so module scope is NOT
 * one-per-page. A duplicated registry silently splits service and field
 * lookups; ``module_loader`` ships a ``rebind`` beacon precisely because that
 * failure is otherwise invisible.
 *
 * Each of those modules previously rolled its own anchor, in five different
 * spellings — plain ``??=`` on a named global, a ``?? (x = …)`` long form, a
 * module-private key constant indexed off ``globalThis``, and two variants
 * wrapped in an ``any`` cast — under four different naming conventions
 * (``__odooRegistry__``, ``__odooTemplates__``, ``__odoo_assets_state__``,
 * ``__odoo_uid_state__``), with no shared place to look them up. This gives
 * the invariant one name and one implementation.
 *
 * Semantics match ``x ??= factory()`` exactly: ``factory`` runs at most once
 * per page, and a stored ``null``/``undefined`` is replaced.
 *
 * @template T
 * @param {string} key stable identifier, unique across addons
 * @param {() => T} factory builds the instance on first call
 * @returns {T}
 */
export function globalSingleton(key, factory) {
    const root = /** @type {Record<string, Record<string, any>>} */ (
        /** @type {any} */ (globalThis)
    );
    const store = (root[NAMESPACE] ??= Object.create(null));
    return (store[key] ??= factory());
}
