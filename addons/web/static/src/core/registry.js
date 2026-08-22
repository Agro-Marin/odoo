// @ts-check
/** @odoo-module native */

import { EventBus, onWillDestroy, useState, validate } from "@odoo/owl";
import { reportJsError } from "@web/core/errors/error_beacon";
import { makeAssetLog } from "@web/core/utils/asset_log";
import { globalSingleton } from "@web/core/utils/global_singleton";

const log = makeAssetLog("registry");

class KeyNotFoundError extends Error {}

/**
 * @param {string} message
 */
function reportRegistryAnomaly(message) {
    console.warn(`[registry] ${message}`);
    reportJsError({ message: `[registry] ${message}`, filename: "@web/core/registry" });
}

/**
 * @param {string | undefined} name
 * @param {string} key
 * @param {any} value
 * @param {object | ((value: any) => boolean | void)} schema
 * @returns {boolean}
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
 * @template T
 */
export class Registry extends EventBus {
    /**
     * @param {string} [name]
     */
    constructor(name) {
        super();
        /**
         * @type {Record<string, [number, GetRegistryItemShape<T>, number]>}
         */
        this.content = Object.create(null);
        /**
         * @type {number}
         */
        this._insertionIndex = 0;
        /**
         * @type {{ [P in keyof GetRegistryCategories<T>]?: Registry<GetRegistryCategories<T>[P]> }}
         */
        this.subRegistries = Object.create(null);
        /** @type {GetRegistryItemShape<T>[] | null} */
        this.elements = null;
        /** @type {[string, GetRegistryItemShape<T>][] | null} */
        this.entries = null;
        this.name = name;
        this.validationSchema = null;

        this.addEventListener("UPDATE", () => {
            this.elements = null;
            this.entries = null;
        });
    }

    /**
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
                const msg =
                    `Duplicate add for key "${key}" in "${this.name || "(root)"}" registry with a different value (first registration wins). ` +
                    `This may indicate either a cross-bundle inline (harmless) or an addon collision (bug).`;
                if (odoo.debug) {
                    console.warn(`[registry] ${msg}`);
                } else {
                    reportRegistryAnomaly(msg);
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
     * @param {string} key
     * @returns {boolean}
     */
    contains(key) {
        return key in this.content;
    }

    /**
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
     * @template {keyof GetRegistryCategories<T> & string} K
     * @param {K} subcategory
     * @returns {Registry<GetRegistryCategories<T>[K]>}
     */
    category(subcategory) {
        if (!Object.hasOwn(this.subRegistries, subcategory)) {
            this.subRegistries[subcategory] = new Registry(subcategory);
            log("category-open", subcategory, "parent=", this.name || "(root)");
        }
        return /** @type {Registry<GetRegistryCategories<T>[K]>} */ (
            this.subRegistries[subcategory]
        );
    }

    /**
     * @param {object | ((value: any) => boolean | void)} schema
     */
    addValidation(schema) {
        if (this.validationSchema) {
            if (this.validationSchema !== schema) {
                reportRegistryAnomaly(
                    `Ignored a second validation schema for the "${this.name || "(root)"}" registry; the first one stays in force.`,
                );
            }
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
