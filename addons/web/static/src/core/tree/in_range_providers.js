// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

export const inRangeProviderRegistry = registry.category("in_range_providers");

/**
 * Ask one provider one question. A provider that throws contributes nothing
 * and says so once, whichever of the entry points below asked.
 *
 * Before, only getInRangeProviderOptions() had a try/catch. A provider that
 * threw was therefore invisible when listing options and fatal when resolving
 * one -- the operator disappeared from the dropdown but crashed the editor if it
 * was already in the domain.
 *
 * @template T
 * @param {string} what
 * @param {string} name
 * @param {any} provider
 * @param {(provider: any) => T | undefined} ask
 * @returns {T | undefined}
 */
function askProvider(what, name, provider, ask) {
    try {
        return ask(provider);
    } catch (error) {
        console.warn(
            `in_range provider "${name}" failed while computing ${what}`,
            error,
        );
        return undefined;
    }
}

/**
 * The first non-empty answer, in registry order.
 *
 * @template T
 * @param {string} what
 * @param {(provider: any) => T | undefined | null | false} ask
 * @returns {T | null}
 */
function firstProviderAnswer(what, ask) {
    for (const [name, provider] of inRangeProviderRegistry.getEntries()) {
        const value = askProvider(what, name, provider, ask);
        if (value) {
            return value;
        }
    }
    return null;
}

/**
 * @param {string} fieldType
 * @returns {Array<{id: string, label: string, group: string}>}
 */
export function getInRangeProviderOptions(fieldType) {
    /** @type {Array<{id: string, label: string, group: string}>} */
    const options = [];
    for (const [name, provider] of inRangeProviderRegistry.getEntries()) {
        const providerOptions =
            askProvider("options", name, provider, (p) => p.getOptions?.(fieldType)) ||
            [];
        for (const option of providerOptions) {
            options.push({
                id: option.id,
                label: option.label,
                group: option.group
                    ? `${provider.label} / ${option.group}`
                    : String(provider.label),
            });
        }
    }
    return options;
}

/**
 * @param {string} id
 * @param {string} fieldType
 * @returns {[any, any] | null}
 */
export function resolveInRangeProviderOption(id, fieldType) {
    return firstProviderAnswer("bounds", (provider) =>
        provider.resolve?.(id, fieldType),
    );
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function matchInRangeProviderOption(fieldType, start, end) {
    return firstProviderAnswer("a match", (provider) =>
        provider.match?.(fieldType, start, end),
    );
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function describeInRangeProviderOption(fieldType, start, end) {
    return firstProviderAnswer("a label", (provider) => {
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
    });
}
