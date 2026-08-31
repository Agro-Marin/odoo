// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

export const inRangeProviderRegistry = registry.category("in_range_providers");

/**
 * Ask every provider one question, and treat a provider that throws the same way
 * in all four entry points below: it contributes nothing, and it says so once.
 *
 * Before, only getInRangeProviderOptions() had a try/catch. A provider that
 * threw was therefore invisible when listing options and fatal when resolving
 * one -- the operator disappeared from the dropdown but crashed the editor if it
 * was already in the domain.
 *
 * @template T
 * @param {string} what
 * @param {(provider: any) => T | undefined} ask
 * @param {(value: T, provider: any) => boolean} keep
 * @param {(value: T, provider: any) => void} take
 */
function eachProvider(what, ask, keep, take) {
    for (const [name, provider] of inRangeProviderRegistry.getEntries()) {
        let value;
        try {
            value = ask(provider);
        } catch (error) {
            console.warn(
                `in_range provider "${name}" failed while computing ${what}`,
                error,
            );
            continue;
        }
        if (value !== undefined && value !== null && keep(value, provider)) {
            take(value, provider);
            return true;
        }
    }
    return false;
}

/**
 * @param {string} fieldType
 * @returns {Array<{id: string, label: string, group: string}>}
 */
export function getInRangeProviderOptions(fieldType) {
    /** @type {Array<{id: string, label: string, group: string}>} */
    const options = [];
    eachProvider(
        "options",
        (provider) => provider.getOptions?.(fieldType) || [],
        (providerOptions, provider) => {
            for (const option of providerOptions) {
                options.push({
                    id: option.id,
                    label: option.label,
                    group: option.group
                        ? `${provider.label} / ${option.group}`
                        : String(provider.label),
                });
            }
            return false; // never short-circuit: every provider contributes
        },
        () => {},
    );
    return options;
}

/**
 * @param {string} id
 * @param {string} fieldType
 * @returns {[any, any] | null}
 */
export function resolveInRangeProviderOption(id, fieldType) {
    /** @type {[any, any] | null} */
    let bounds = null;
    eachProvider(
        "bounds",
        (provider) => provider.resolve?.(id, fieldType),
        (value) => Boolean(value),
        (value) => {
            bounds = value;
        },
    );
    return bounds;
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function matchInRangeProviderOption(fieldType, start, end) {
    /** @type {string | null} */
    let matched = null;
    eachProvider(
        "a match",
        (provider) => provider.match?.(fieldType, start, end),
        (id) => Boolean(id),
        (id) => {
            matched = id;
        },
    );
    return matched;
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function describeInRangeProviderOption(fieldType, start, end) {
    /** @type {string | null} */
    let label = null;
    eachProvider(
        "a label",
        (provider) => {
            const id = provider.match?.(fieldType, start, end);
            if (!id) {
                return undefined;
            }
            // Ask the provider that matched for its own label rather than
            // rebuilding every provider's option list to look one up.
            const option = (provider.getOptions?.(fieldType) || []).find(
                (/** @type {any} */ o) => o.id === id,
            );
            return option ? String(option.label) : undefined;
        },
        (value) => Boolean(value),
        (value) => {
            label = value;
        },
    );
    return label;
}
