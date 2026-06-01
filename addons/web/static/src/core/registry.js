// @ts-check
/** @odoo-module native */

/** @module @web/core/registry - Hierarchical key-value store for services, components, fields, and actions */

import { EventBus, onWillDestroy, onWillStart, useState, validate } from "@odoo/owl";
import { makeAssetLog } from "@web/core/utils/asset_log";

const log = makeAssetLog("registry");

// -----------------------------------------------------------------------------
// Errors
// -----------------------------------------------------------------------------
export class KeyNotFoundError extends Error {}

export class DuplicatedKeyError extends Error {}

// -----------------------------------------------------------------------------
// Validation
// -----------------------------------------------------------------------------

/**
 * @param {string} name
 * @param {string} key
 * @param {any} value
 * @param {object} schema
 */
const validateSchema = (name, key, value, schema) => {
    let error;
    try {
        if (typeof schema === "function") {
            // Function predicate: registries holding bare functions
            // (formatters, parsers, error_handlers, …) cannot express
            // their contract via OWL's object-shape ``validate``, so
            // ``addValidation`` also accepts a predicate. Returning
            // ``false`` flags the entry as invalid; ``undefined`` /
            // truthy accepts it.
            if (schema(value) === false) {
                error = new Error(`value did not pass the predicate`);
            }
        } else {
            validate(value, schema);
        }
    } catch (e) {
        error = e;
    }
    if (!error) {
        return;
    }
    const msg = `Validation error for key "${key}" in registry "${name}": ${error}`;
    if (odoo.debug) {
        // Dev: fail-fast so the bad registration cannot enter the registry.
        throw new Error(msg, { cause: error });
    }
    // Production: warn instead of throwing so a single bad registration
    // cannot crash the page. Operators get visibility into latent schema
    // mismatches that previously shipped silently. Pre-2026-05 the
    // validation step short-circuited entirely outside debug mode, so
    // any third-party module shipping a malformed entry kept working
    // and the bug only surfaced when a developer happened to enable
    // debug. The warning lifts that signal into production logs.
    console.warn(`[registry] ${msg}`);
};

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * @template S
 * @template C
 * @typedef {import("registries").RegistryData<S, C>} RegistryData
 */

/**
 * @template T
 * @typedef {T extends RegistryData<any, any> ? T : RegistryData<T, {}>} ToRegistryData
 */

/**
 * @template T
 * @typedef {ToRegistryData<T>["__itemShape"]} GetRegistryItemShape
 */

/**
 * @template T
 * @typedef {ToRegistryData<T>["__categories"]} GetRegistryCategories
 */

/**
 * Registry
 *
 * The Registry class is basically just a mapping from a string key to an object.
 * It is really not much more than an object. It is however useful for the
 * following reasons:
 *
 * 1. it let us react and execute code when someone add something to the registry
 *   (for example, the FunctionRegistry subclass this for this purpose)
 * 2. it throws an error when the get operation fails
 * 3. it provides a chained API to add items to the registry.
 *
 * @template T
 */
export class Registry extends EventBus {
    /**
     * @param {string} [name]
     */
    constructor(name) {
        super();
        /**
         * Null-prototype object prevents false positives from inherited
         * keys like "constructor" or "toString" in contains()/get().
         * @type {Record<string, [number, GetRegistryItemShape<T>]>}
         */
        this.content = Object.create(null);
        /** @type {{ [P in keyof GetRegistryCategories<T>]?: Registry<GetRegistryCategories<T>[P]> }} */
        this.subRegistries = {};
        /** @type {GetRegistryItemShape<T>[]}*/
        this.elements = null;
        /** @type {[string, GetRegistryItemShape<T>][]}*/
        this.entries = null;
        this.name = name;
        this.validationSchema = null;

        this.addEventListener("UPDATE", () => {
            this.elements = null;
            this.entries = null;
        });
    }

    /**
     * Add an entry (key, value) to the registry if key is not already used. If
     * the parameter force is set to true, an entry with same key (if any) is replaced.
     *
     * Note that this also returns the registry, so another add method call can
     * be chained
     *
     * @param {string} key
     * @param {GetRegistryItemShape<T>} value
     * @param {{force?: boolean, sequence?: number}} [options]
     * @returns {Registry<T>}
     */
    add(key, value, { force, sequence } = {}) {
        if (this.validationSchema) {
            validateSchema(this.name, key, value, this.validationSchema);
        }
        if (!force && key in this.content) {
            // Multiple ESM bundles each inline their own copy of the same
            // ``@<addon>/...`` modules (web.assets_tests bundles a transitive
            // copy of @web/core/ui/ui_service alongside web.assets_web's own
            // copy).  With a shared registry instance, both bundles' top-level
            // ``add()`` calls hit the same Map.  First-wins semantics make
            // that work: web.assets_web evaluates first (its <script type=
            // "module"> is rendered earlier in the document), so its instance
            // owns the slot.  Subsequent same-key adds are silently no-ops.
            //
            // This intentionally relaxes the historical "explicit guard
            // against name collisions" — the trade-off is documented in
            // task #5 of the test-suite-validation deuda técnica notes.
            // True conflicts (different addons claiming the same key) still
            // surface via runtime behavior (the wrong implementation wins).
            //
            // In ``odoo.debug`` mode we additionally emit a console.warn on
            // *different-value* duplicates so developers can investigate
            // whether the duplicate is a benign cross-bundle inline or a
            // genuine cross-addon collision.  Production stays silent to
            // preserve the cross-bundle behavior unchanged.
            if (this.content[key][1] !== value) {
                if (odoo.debug) {
                    console.warn(
                        `[registry] Duplicate add for key "${key}" in "${this.name || "(root)"}" registry with a different value (first registration wins). ` +
                        `This may indicate either a cross-bundle inline (harmless) or an addon collision (bug).`,
                    );
                }
                return this;
            }
            return this;
        }
        let previousSequence;
        if (force) {
            const elem = this.content[key];
            previousSequence = elem && elem[0];
        }
        sequence = sequence ?? previousSequence ?? 50;
        this.content[key] = [sequence, value];
        const payload = { operation: "add", key, value };
        this.trigger("UPDATE", payload);
        return this;
    }

    /**
     * Get an item from the registry
     *
     * @param {string} key
     * @param {GetRegistryItemShape<T>} [defaultValue]
     * @returns {GetRegistryItemShape<T>}
     */
    get(key, defaultValue) {
        if (arguments.length < 2 && !(key in this.content)) {
            throw new KeyNotFoundError(
                `Cannot find key "${key}" in the "${this.name}" registry`,
            );
        }
        const info = this.content[key];
        return info ? info[1] : defaultValue;
    }

    /**
     * Check the presence of a key in the registry
     *
     * @param {string} key
     * @returns {boolean}
     */
    contains(key) {
        return key in this.content;
    }

    /**
     * Get a list of all elements in the registry. Note that it is ordered
     * according to the sequence numbers.
     *
     * Returns a frozen cached array — callers that need a mutable copy
     * should spread it: ``[...registry.getAll()]``.
     *
     * @returns {ReadonlyArray<GetRegistryItemShape<T>>}
     */
    getAll() {
        if (!this.elements) {
            const tuples = Object.values(this.content);
            tuples.sort((a, b) => a[0] - b[0]);
            const elements = new Array(tuples.length);
            for (let i = 0; i < tuples.length; i++) {
                elements[i] = tuples[i][1];
            }
            this.elements = /** @type {any} */ (Object.freeze(elements));
        }
        return this.elements;
    }

    /**
     * Return a list of all entries, ordered by sequence numbers.
     *
     * Returns a frozen cached array — callers that need a mutable copy
     * should spread it: ``[...registry.getEntries()]``.
     *
     * @returns {ReadonlyArray<[string, GetRegistryItemShape<T>]>}
     */
    getEntries() {
        if (!this.entries) {
            const raw = Object.entries(this.content);
            raw.sort((a, b) => a[1][0] - b[1][0]);
            const entries = new Array(raw.length);
            for (let i = 0; i < raw.length; i++) {
                entries[i] = [raw[i][0], raw[i][1][1]];
            }
            this.entries = /** @type {any} */ (Object.freeze(entries));
        }
        return this.entries;
    }

    /**
     * Remove an item from the registry.
     * No-op if the key does not exist.
     *
     * @param {string} key
     */
    remove(key) {
        if (!(key in this.content)) {
            return;
        }
        const value = this.content[key][1];
        delete this.content[key];
        const payload = { operation: "delete", key, value };
        this.trigger("UPDATE", payload);
    }

    /**
     * Open a sub registry (and create it if necessary)
     *
     * @template {keyof GetRegistryCategories<T> & string} K
     * @param {K} subcategory
     * @returns {Registry<GetRegistryCategories<T>[K]>}
     */
    category(subcategory) {
        if (!(subcategory in this.subRegistries)) {
            this.subRegistries[subcategory] = new Registry(subcategory);
            log("category-open", subcategory,
                "parent=", this.name || "(root)");
        }
        return this.subRegistries[subcategory];
    }

    /**
     * Set a validation schema for this registry. All existing and future
     * entries will be validated against it.
     *
     * Two schema forms are supported:
     *
     *   - **object** — passed straight to OWL's ``validate(value, schema)``.
     *     Use for entries shaped like ``{ component, extractProps, ... }``
     *     where each property has its own type (the existing pattern;
     *     6 categories use this form: ``services``, ``fields``, ``views``,
     *     ``view_widgets``, ``main_components``, plus the registry primitive
     *     itself).
     *
     *   - **function predicate** — invoked as ``schema(value)``; a return
     *     of ``false`` flags the entry as invalid, anything else (including
     *     ``undefined`` / truthy) accepts it. Use for registries holding
     *     bare functions (``formatters``, ``parsers``, ``error_handlers``,
     *     ``error_notifications``, ...) where OWL's object-shape validator
     *     cannot express the contract.
     *
     * Validation behavior in both forms: ``odoo.debug`` mode throws on
     * invalid entries (fail-fast); production logs ``console.warn`` so
     * a single bad registration does not crash the page.
     *
     * @param {object | ((value: any) => boolean | void)} schema
     */
    addValidation(schema) {
        if (this.validationSchema) {
            // Idempotent: with the ``globalThis``-anchored shared registry,
            // multiple bundles each evaluate the source file that declares
            // the validation schema for a given category and call
            // ``addValidation`` on the same Registry instance.  First-wins
            // semantics — silently keep the existing schema.  Different
            // schemas registered for the same registry would still be a
            // bug at the design level (two competing validators), but since
            // the bundle-evaluation order in the browser is deterministic
            // (web.assets_web first), the FIRST schema wins consistently
            // across page loads.
            return;
        }
        this.validationSchema = schema;
        for (const [key, value] of this.getEntries()) {
            validateSchema(this.name, key, value, schema);
        }
    }
}

// Anchor the global ``registry`` on ``globalThis`` so ESM bundles which
// each inline their own copy of this module (web.assets_web bundles the
// canonical registry; web.assets_tests, web.assets_unit_tests, and every
// DYNAMIC_ESM_BUNDLES child build separately and inline their own copies)
// observe the SAME ``Registry`` instance instead of running with private
// ones.  Without this anchor, code that registers into
// ``registry.category("web_tour.tours")`` from a tour file in the
// ``web.assets_tests`` bundle writes to the test bundle's private
// registry, while ``odoo.isTourReady`` (defined in ``web_tour`` and
// loaded with ``web.assets_web``) reads the parent bundle's registry —
// the tour is never found and every browser-tour test times out on the
// ready check.  ``??=`` keeps the FIRST bundle's instance authoritative
// (typically ``web.assets_web``, which evaluates first).
//
// Multiple bundles re-evaluating the same source file (e.g. both bundles
// inlining ``@web/core/ui/ui_service``) would now hit the SAME registry
// with duplicate ``add("ui", …)`` calls.  ``Registry.add`` is silently
// idempotent on duplicate keys — see the comment above.
/** @type {Registry<import("registries").GlobalRegistry>} */
export const registry = (globalThis.__odooRegistry__ ??= new Registry());

// ---------------------------------------------------------------------------
// Registry hook (merged from registry_hook.js)
// ---------------------------------------------------------------------------

/**
 * OWL hook that provides a reactive view of a registry's entries.
 * Re-renders the component when entries are added or removed.
 *
 * The returned ``entries`` array is a mutable reactive copy — callers like
 * {@link MainComponentsContainer.handleComponentError} may splice it directly
 * to remove faulty entries without touching the underlying registry.
 *
 * Uses incremental updates (not full replacement) so that entries removed
 * locally by error handlers are not restored by subsequent registry changes.
 *
 * @template T
 * @param {Registry<T>} registry
 * @returns {{ entries: [string, GetRegistryItemShape<T>][] }}
 */
export function useRegistry(registry) {
    const state = useState({ entries: [...registry.getEntries()] });
    const listener = ({ detail }) => {
        const index = state.entries.findIndex(([k]) => k === detail.key);
        if (detail.operation === "add") {
            const newEntries = registry.getEntries();
            const newIndex = newEntries.findIndex(([k]) => k === detail.key);
            if (newIndex === -1) {
                return;
            }
            if (index !== -1) {
                // Force-replace: remove old, insert at new position.
                state.entries.splice(index, 1);
            }
            state.entries.splice(newIndex, 0, newEntries[newIndex]);
        } else if (detail.operation === "delete" && index >= 0) {
            state.entries.splice(index, 1);
        }
    };

    onWillStart(() =>
        registry.addEventListener("UPDATE", /** @type {any} */ (listener)),
    );
    onWillDestroy(() =>
        registry.removeEventListener("UPDATE", /** @type {any} */ (listener)),
    );
    return state;
}
