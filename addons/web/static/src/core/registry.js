// @ts-check
/** @odoo-module native */

/** @module @web/core/registry - Hierarchical key-value store for services, components, fields, and actions */

import { EventBus, onWillDestroy, useState, validate } from "@odoo/owl";
import { reportJsError } from "@web/core/errors/error_beacon";
import { makeAssetLog } from "@web/core/utils/asset_log";

const log = makeAssetLog("registry");

// -----------------------------------------------------------------------------
// Errors
// -----------------------------------------------------------------------------
export class KeyNotFoundError extends Error {}

// -----------------------------------------------------------------------------
// Validation
// -----------------------------------------------------------------------------

/**
 * @param {string | undefined} name
 * @param {string} key
 * @param {any} value
 * @param {object} schema
 */
/**
 * Report a registry-integrity anomaly (e.g. a quarantined invalid entry).
 * Routed through ``error_beacon`` so it lands in the same observability
 * endpoint as JS errors; ``console.warn`` is the always-on signal, the
 * beacon a best-effort upgrade (``reportJsError`` never throws).
 *
 * @param {string} message
 */
function reportRegistryAnomaly(message) {
    console.warn(`[registry] ${message}`);
    reportJsError({ message: `[registry] ${message}`, filename: "@web/core/registry" });
}

/**
 * Validate a candidate entry against the registry's schema.
 *
 * - valid (or no schema)     → ``true`` (caller inserts).
 * - invalid + ``odoo.debug`` → throws (fail-fast, never inserted).
 * - invalid + production     → ``false`` (quarantined, not inserted) and
 *   an anomaly is reported. Previously an invalid entry was inserted
 *   anyway and merely warned; quarantining keeps the invariant "every
 *   stored entry satisfies the schema" intact everywhere, and a consumer
 *   of a quarantined key gets a clear ``KeyNotFoundError`` instead of
 *   corrupt data.
 *
 * @param {string | undefined} name
 * @param {string} key
 * @param {any} value
 * @param {object | ((value: any) => boolean | void)} schema
 * @returns {boolean} true if the entry should be inserted
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
        return true;
    }
    const msg = `Validation error for key "${key}" in registry "${name}": ${error}`;
    if (odoo.debug) {
        // Dev: fail-fast so the bad registration cannot enter the registry.
        throw new Error(msg, { cause: error });
    }
    // Production: refuse the entry (quarantine) and report. Keeping the
    // page alive no longer requires serving a known-invalid value.
    reportRegistryAnomaly(msg);
    return false;
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
 * Ordered key-value store with change events, a chainable ``add`` API, and
 * an error on missing ``get``.
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
         * Each entry is ``[sequence, value, insertionIndex]``; the trailing
         * insertion index is the deterministic tiebreaker for equal sequences
         * (see {@link add}).
         * @type {Record<string, [number, GetRegistryItemShape<T>, number]>}
         */
        this.content = Object.create(null);
        /**
         * Monotonic counter stamped onto each inserted entry so equal-sequence
         * entries order by insertion regardless of key shape. Object key
         * enumeration alone is not insertion order — integer-like keys ("2",
         * "10") enumerate in ascending numeric order BEFORE string keys — so
         * a registry keyed by numeric ids would otherwise reorder ties
         * unpredictably. @type {number}
         */
        this._insertionIndex = 0;
        /** @type {{ [P in keyof GetRegistryCategories<T>]?: Registry<GetRegistryCategories<T>[P]> }} */
        this.subRegistries = {};
        /** @type {GetRegistryItemShape<T>[] | null}*/
        this.elements = null;
        /** @type {[string, GetRegistryItemShape<T>][] | null}*/
        this.entries = null;
        this.name = name;
        this.validationSchema = null;

        this.addEventListener("UPDATE", () => {
            this.elements = null;
            this.entries = null;
        });
    }

    /**
     * Add an entry (key, value), replacing any existing one if ``force`` is
     * set. Returns the registry for chaining.
     *
     * @param {string} key
     * @param {GetRegistryItemShape<T>} value
     * @param {{force?: boolean, sequence?: number}} [options]
     * @returns {Registry<T>}
     */
    add(key, value, { force, sequence } = {}) {
        if (this.validationSchema) {
            if (!validateSchema(this.name, key, value, this.validationSchema)) {
                // Production: the entry failed schema validation and was
                // quarantined (not inserted) — see validateSchema. Debug
                // mode already threw. Return chainably without crashing.
                return this;
            }
        }
        if (!force && key in this.content) {
            // Multiple ESM bundles (e.g. web.assets_tests, web.assets_web) each
            // inline this module and race to add() the same key; first-wins
            // keeps that working since web.assets_web evaluates first. Real
            // cross-addon collisions still surface as wrong-impl bugs at
            // runtime (see test-suite-validation notes task #5).
            //
            // Warn in odoo.debug on a different-value duplicate to flag a real
            // collision; stay silent in production to preserve the behavior.
            if (this.content[key][1] !== value) {
                if (odoo.debug) {
                    console.warn(
                        `[registry] Duplicate add for key "${key}" in "${this.name || "(root)"}" registry with a different value (first registration wins). ` +
                            `This may indicate either a cross-bundle inline (harmless) or an addon collision (bug).`,
                    );
                }
                return this;
            }
            // Same value re-registered: the early return keeps the ORIGINAL
            // sequence, so a caller passing a different sequence to reorder
            // has it silently dropped — warn in dev so that isn't a mystery.
            if (
                odoo.debug &&
                sequence !== undefined &&
                sequence !== this.content[key][0]
            ) {
                console.warn(
                    `[registry] Duplicate add for key "${key}" in "${this.name || "(root)"}" registry with the same value but a different sequence ` +
                        `(kept ${this.content[key][0]}, ignored ${sequence}). Use { force: true } to change the sequence.`,
                );
            }
            return this;
        }
        let previousSequence;
        if (force) {
            const elem = this.content[key];
            previousSequence = elem && elem[0];
        }
        sequence = sequence ?? previousSequence ?? 50;
        this.content[key] = [sequence, value, this._insertionIndex++];
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
                `Cannot find key "${key}" in the "${this.name || "(root)"}" registry`,
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
            // Sequence first, then insertion index so equal sequences keep
            // add() order deterministically (Object.values enumeration would
            // otherwise put integer-like keys ahead of string keys).
            tuples.sort((a, b) => a[0] - b[0] || a[2] - b[2]);
            const elements = new Array(tuples.length);
            for (let i = 0; i < tuples.length; i++) {
                elements[i] = tuples[i][1];
            }
            this.elements = /** @type {any} */ (Object.freeze(elements));
        }
        // Non-null after the cache-fill above; the field is nullable only to
        // model the "needs recompute" reset performed by the UPDATE listener.
        return /** @type {ReadonlyArray<GetRegistryItemShape<T>>} */ (this.elements);
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
            // See getAll(): sequence, then insertion index for stable ties.
            raw.sort((a, b) => a[1][0] - b[1][0] || a[1][2] - b[1][2]);
            const entries = new Array(raw.length);
            for (let i = 0; i < raw.length; i++) {
                entries[i] = [raw[i][0], raw[i][1][1]];
            }
            this.entries = /** @type {any} */ (Object.freeze(entries));
        }
        // Non-null after the cache-fill above (see getAll).
        return /** @type {ReadonlyArray<[string, GetRegistryItemShape<T>]>} */ (
            this.entries
        );
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
            log("category-open", subcategory, "parent=", this.name || "(root)");
        }
        return /** @type {Registry<GetRegistryCategories<T>[K]>} */ (
            this.subRegistries[subcategory]
        );
    }

    /**
     * Set a validation schema for this registry; existing and future
     * entries are validated against it.
     *
     * Two forms: an **object**, passed to OWL's ``validate(value, schema)``
     * (for shaped entries like ``{ component, extractProps, ... }``), or a
     * **function predicate** ``schema(value)`` returning ``false`` to flag
     * an entry invalid (for registries of bare functions where OWL's
     * object-shape validator doesn't apply, e.g. ``formatters``, ``parsers``).
     *
     * ``odoo.debug`` throws on invalid entries; production quarantines them
     * (see ``validateSchema``).
     *
     * @param {object | ((value: any) => boolean | void)} schema
     */
    addValidation(schema) {
        if (this.validationSchema) {
            // Idempotent: multiple bundles sharing the globalThis-anchored
            // registry each call addValidation for the same category.
            // First-wins keeps this deterministic (web.assets_web evaluates
            // first), silently discarding later calls.
            return;
        }
        this.validationSchema = schema;
        for (const [key, value] of this.getEntries()) {
            if (!validateSchema(this.name, key, value, schema)) {
                // Retroactively quarantine an already-registered entry that
                // violates the new schema. Safe to mutate while iterating:
                // getEntries() is a frozen snapshot; debug mode already
                // threw inside validateSchema.
                this.remove(key);
            }
        }
    }
}

// Anchor the global ``registry`` on ``globalThis`` so every ESM bundle that
// inlines this module (web.assets_web, web.assets_tests, web.assets_unit_tests,
// esm.dynamic_children, ...) shares the SAME instance. Without this, a tour
// registered from web.assets_tests would write to that bundle's private
// registry while ``odoo.isTourReady`` (web.assets_web) reads a different one —
// the tour is never found and the browser-tour test times out. ``??=`` keeps
// the FIRST bundle's instance authoritative (typically web.assets_web).
//
// Duplicate ``add("ui", …)`` calls from bundles inlining the same source now
// hit one registry — see Registry.add's idempotent-duplicate handling above.
/** @type {Registry<import("registries").GlobalRegistry>} */
export const registry = /** @type {any} */ (
    globalThis.__odooRegistry__ ??= new Registry()
);

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
    const listener = (
        /** @type {{ detail: { key: string, operation: string } }} */ { detail },
    ) => {
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
            // ``state.entries`` may have diverged from the full registry
            // ordering (error handlers splice entries out locally), so the
            // full-order index can overshoot. Map full order → local order:
            // insert before the first local entry that sorts after the new
            // key in the registry's ordering.
            const followers = new Set(newEntries.slice(newIndex + 1).map(([k]) => k));
            let insertAt = state.entries.findIndex(([k]) => followers.has(k));
            if (insertAt === -1) {
                insertAt = state.entries.length;
            }
            state.entries.splice(insertAt, 0, newEntries[newIndex]);
        } else if (detail.operation === "delete" && index >= 0) {
            state.entries.splice(index, 1);
        }
    };

    // Attach at setup time (not onWillStart): an "add" landing between setup
    // and an async willStart chain would otherwise be lost — the snapshot
    // above is taken now, so listening must start now too.
    registry.addEventListener("UPDATE", /** @type {any} */ (listener));
    onWillDestroy(() =>
        registry.removeEventListener("UPDATE", /** @type {any} */ (listener)),
    );
    return state;
}
