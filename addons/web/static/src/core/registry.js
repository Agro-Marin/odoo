// @ts-check
/** @odoo-module native */

/** @module @web/core/registry - Hierarchical key-value store for services, components, fields, and actions */

import { EventBus, onWillDestroy, useState, validate } from "@odoo/owl";
import { reportJsError } from "@web/core/errors/error_beacon";
import { makeAssetLog } from "@web/core/utils/asset_log";
import { globalSingleton } from "@web/core/utils/global_singleton";

const log = makeAssetLog("registry");

export class KeyNotFoundError extends Error {}

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
        throw new Error(msg, { cause: error });
    }
    reportRegistryAnomaly(msg);
    return false;
};

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
         * unpredictably.
         *
         * A key's ordinal is stamped at FIRST registration and preserved by a
         * ``force`` override (see {@link add}), which is the whole point: a
         * ``{ force: true }`` re-add is how an addon overrides an existing
         * entry, and re-stamping would silently move that entry behind its
         * equal-sequence peers — reordering first-match-wins registries such
         * as ``error_handlers``. @type {number}
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
                return this;
            }
        }
        if (!force && key in this.content) {
            if (this.content[key][1] !== value) {
                if (odoo.debug) {
                    console.warn(
                        `[registry] Duplicate add for key "${key}" in "${this.name || "(root)"}" registry with a different value (first registration wins). ` +
                            `This may indicate either a cross-bundle inline (harmless) or an addon collision (bug).`,
                    );
                }
                return this;
            }
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
        let previousInsertion;
        if (force) {
            const elem = this.content[key];
            if (elem) {
                previousSequence = elem[0];
                previousInsertion = elem[2];
            }
        }
        sequence = sequence ?? previousSequence ?? 50;
        this.content[key] = [
            sequence,
            value,
            previousInsertion ?? this._insertionIndex++,
        ];
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
     * Get a list of all elements in the registry, ordered by sequence
     * number.
     *
     * Returns a frozen cached array — callers that need a mutable copy
     * should spread it: ``[...registry.getAll()]``.
     *
     * @returns {ReadonlyArray<GetRegistryItemShape<T>>}
     */
    getAll() {
        if (!this.elements) {
            const tuples = Object.values(this.content);
            tuples.sort((a, b) => a[0] - b[0] || a[2] - b[2]);
            const elements = new Array(tuples.length);
            for (let i = 0; i < tuples.length; i++) {
                elements[i] = tuples[i][1];
            }
            this.elements = /** @type {any} */ (Object.freeze(elements));
        }
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
            raw.sort((a, b) => a[1][0] - b[1][0] || a[1][2] - b[1][2]);
            const entries = new Array(raw.length);
            for (let i = 0; i < raw.length; i++) {
                entries[i] = [raw[i][0], raw[i][1][1]];
            }
            this.entries = /** @type {any} */ (Object.freeze(entries));
        }
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
            return;
        }
        this.validationSchema = schema;
        for (const [key, value] of this.getEntries()) {
            if (!validateSchema(this.name, key, value, schema)) {
                this.remove(key);
            }
        }
    }
}

/** @type {Registry<import("registries").GlobalRegistry>} */
export const registry = /** @type {any} */ (
    globalSingleton("registry", () => new Registry())
);

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
                state.entries.splice(index, 1);
            }
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

    registry.addEventListener("UPDATE", /** @type {any} */ (listener));
    onWillDestroy(() =>
        registry.removeEventListener("UPDATE", /** @type {any} */ (listener)),
    );
    return state;
}
