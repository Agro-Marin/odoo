// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

export const inRangeProviderRegistry = registry.category("in_range_providers");

/**
 * @param {string} fieldType
 * @returns {Array<{id: string, label: string, group: string}>}
 */
export function getInRangeProviderOptions(fieldType) {
    const options = [];
    for (const [, provider] of inRangeProviderRegistry.getEntries()) {
        let providerOptions;
        try {
            providerOptions = provider.getOptions?.(fieldType) || [];
        } catch {
            providerOptions = [];
        }
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
    for (const [, provider] of inRangeProviderRegistry.getEntries()) {
        const bounds = provider.resolve?.(id, fieldType);
        if (bounds) {
            return bounds;
        }
    }
    return null;
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function matchInRangeProviderOption(fieldType, start, end) {
    for (const [, provider] of inRangeProviderRegistry.getEntries()) {
        const id = provider.match?.(fieldType, start, end);
        if (id) {
            return id;
        }
    }
    return null;
}

/**
 * @param {string} fieldType
 * @param {any} start
 * @param {any} end
 * @returns {string | null}
 */
export function describeInRangeProviderOption(fieldType, start, end) {
    const id = matchInRangeProviderOption(fieldType, start, end);
    if (!id) {
        return null;
    }
    const option = getInRangeProviderOptions(fieldType).find((o) => o.id === id);
    return option ? String(option.label) : null;
}
