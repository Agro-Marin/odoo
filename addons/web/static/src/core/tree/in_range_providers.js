// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/in_range_providers */

import { registry } from "@web/core/registry";

/**
 * Named periods offered by an addon in the `in range` value editor.
 *
 * A provider contributes *named* spans — a fiscal year, a season, a campaign —
 * on top of the calendar and rolling options `IN_RANGE_OPTIONS` already lists.
 *
 * A named period is deliberately NOT a new value type. A period and a custom
 * range serialize to the same domain: `[("date", ">=", a), ("date", "<=", b)]`
 * is both "Q1 2024" and "1 January to 31 March", and nothing in the domain
 * distinguishes them. An addon that gives itself a separate operator therefore
 * has to claim a domain shape this one does not — which is why the first
 * implementation of this feature emitted `<=` before `>=` and could never
 * recover which period a stored domain meant.
 *
 * So a provider option resolves to a plain `custom range` value on the way in,
 * and is recovered on the way out by matching the stored bounds back against
 * the known periods. The domain is unchanged and unambiguous; only the editor
 * shows a name instead of two dates.
 *
 * A provider is a plain object:
 *
 *   {
 *     // optgroup label for this provider's options; may be a plain string
 *     label: _t("Periods"),
 *
 *     // named periods available for a field of this type. `group` is
 *     // optional and subdivides the provider's own optgroup.
 *     getOptions(fieldType) {
 *         return [{ id: "date_range:7", label: "Q1 2024", group: "Fiscal" }];
 *     },
 *
 *     // option id -> the [start, end] pair a `custom range` holds
 *     resolve(id, fieldType) { return ["2024-01-01", "2024-03-31"]; },
 *
 *     // the inverse: bounds -> option id, or null when they name no period
 *     match(fieldType, start, end) { return "date_range:7"; },
 *   }
 *
 * Every method is synchronous. A provider whose data comes from the server is
 * responsible for having loaded it before the editor renders; `getOptions`
 * returning `[]` degrades to the built-in options with nothing broken.
 *
 * Option ids must not collide with the built-in value types, so prefix them
 * with the addon name.
 */
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
            // A provider that throws must not take the domain editor with it:
            // the built-in options are still a usable editor on their own.
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
 * Resolve a provider option id to the bounds a `custom range` holds.
 *
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
 * Recover the provider option a pair of bounds names, if any.
 *
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
 * The human label for the period a pair of bounds names, for read-only
 * descriptions of a condition.
 *
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
