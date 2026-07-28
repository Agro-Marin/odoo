// @ts-check
/** @odoo-module native */

/** @module @web/services/currency - Currency lookup, formatting, and exchange rate fetching */

import { reactive } from "@odoo/owl";
import { UserEvent } from "@web/core/events";
import { parseDate } from "@web/core/l10n/dates";
import { rpc } from "@web/core/network/rpc";
import { formatFloat, humanNumber } from "@web/core/utils/format/numbers";
import { nbsp } from "@web/core/utils/format/strings";
import { user, userBus } from "@web/services/user";
import { session } from "@web/session";

/** @type {Record<number, {symbol: string, position: string, digits: [number, number]}>} */
export const currencies = session.currencies || {};
delete session.currencies;

/**
 * Look up a currency definition by its database ID.
 * @param {number} id - res.currency record ID
 * @returns {{symbol: string, position: string, digits: [number, number]} | undefined}
 */
export function getCurrency(id) {
    return currencies[id];
}

/**
 * Shared reactive rates object handed to every getCurrencyRates() caller, so
 * one refresh updates all consumers instead of only the fetch-triggering one.
 * ``date`` is the PARSED Luxon DateTime, not the server's serialized string —
 * {@link applyRates} runs every record through ``parseDate``.
 * @type {Record<number, {rate: number, date: import("@web/core/l10n/dates").NullableDateTime}>}
 */
const rates = reactive({});
/**
 * In-flight fetch, memoized so concurrent callers share one RPC. Cleared on
 * settlement: warm repeats are served by the rpc disk/RAM cache, and a
 * cache invalidation naturally makes the next call refetch fresh rates into
 * the shared object.
 * @type {Promise<void> | null}
 */
let ratesPromise = null;
/**
 * Bumped on every company switch (listener registered below, once ``rates`` and
 * ``ratesPromise`` exist). Rates are expressed against the ACTIVE COMPANY's
 * currency (``to_currency`` in {@link fetchCurrencyRates}), so a switch changes
 * what the numbers MEAN, and a fetch issued BEFORE the switch must not land
 * after it: it would write the old company's conversions over the shared object
 * with no further trigger to correct them.
 */
let ratesEpoch = 0;

/**
 * Replace the shared rates in place (removing vanished currencies) so every
 * held reference observes the update. ``records`` carry the server's
 * serialized date; the stored entry carries the parsed DateTime.
 * @param {Array<{id: number, inverse_rate: number, date: string}>} records
 */
function applyRates(records) {
    const newRates = Object.fromEntries(
        records.map((r) => [
            r.id,
            {
                rate: r.inverse_rate,
                date: parseDate(r.date),
            },
        ]),
    );
    for (const id of Object.keys(rates)) {
        if (!(id in newRates)) {
            delete rates[id];
        }
    }
    Object.assign(rates, newRates);
}

async function fetchCurrencyRates() {
    const epoch = ratesEpoch;
    const model = "res.currency";
    const method = "read";
    const url = `/web/dataset/call_kw/${model}/${method}`;
    const context = {
        ...user.context,
        to_currency: user.activeCompany?.currency_id,
    };
    const params = {
        model,
        method,
        args: [Object.keys(currencies).map(Number), ["inverse_rate", "date"]],
        kwargs: { context },
    };
    const records = await rpc(url, params, {
        cache: {
            type: "disk",
            update: "once",
            callback: (
                /** @type {{id: number, inverse_rate: number, date: string}[]} */ records,
                /** @type {boolean} */ hasChanged,
            ) => {
                if (hasChanged && epoch === ratesEpoch) {
                    applyRates(records);
                }
            },
        },
        retry: 1,
    });
    if (epoch !== ratesEpoch) {
        return;
    }
    applyRates(records);
}

/**
 * Deliberately NOT an eager refetch: a real switch changes ``to_currency``,
 * hence the rpc cache key, so the next consumer call already refetches. Firing
 * one here bought a shorter staleness window at the cost of an RPC on every
 * company switch, including on pages that never show a monetary conversion.
 *
 * Deliberately NOT a clear either: dropping the entries makes every consumer
 * reading ``rates[id].rate`` throw until the refetch lands.
 */
userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, () => {
    ratesEpoch++;
    // Nothing may join an in-flight fetch issued for the previous company.
    ratesPromise = null;
});

/**
 * Fetch inverse exchange rates for all known currencies relative to the
 * active company's currency. All callers receive the SAME reactive object,
 * updated in place when the disk cache detects a change and when a call
 * after a cache invalidation refetches — so long-lived consumers see rate
 * refreshes without refetching themselves.
 * @returns {Promise<Record<number, {rate: number, date: import("@web/core/l10n/dates").NullableDateTime}>>} currency id → rate info
 */
export async function getCurrencyRates() {
    if (!ratesPromise) {
        const prom = fetchCurrencyRates().finally(() => {
            // Only clear the slot this fetch still owns. A company switch nulls
            // `ratesPromise` mid-flight, so an unguarded clear let the OLD fetch
            // evict the NEW one on settling and the next caller re-entered
            // `fetchCurrencyRates` for a fetch already in progress.
            if (ratesPromise === prom) {
                ratesPromise = null;
            }
        });
        ratesPromise = prom;
    }
    await ratesPromise;
    return rates;
}

/**
 * Returns a string representing a monetary value. The result takes into account
 * the user settings (to display the correct decimal separator, currency, ...).
 *
 * @param {number} amount the value that should be formatted
 * @param {number} [currencyId] the id of the 'res.currency' to use
 * @param {any} [options] formatting options (data, noSymbol, humanReadable,
 *   minDigits, trailingZeros, digits)
 * @returns {string}
 */
export function formatCurrency(amount, currencyId, options = {}) {
    const currency = getCurrency(/** @type {number} */ (currencyId));

    const digits = options.digits !== undefined ? options.digits : currency?.digits;

    let formattedAmount;
    if (options.humanReadable) {
        formattedAmount = humanNumber(amount, {
            decimals: digits ? digits[1] : 2,
            minDigits: options.minDigits,
        });
    } else {
        formattedAmount = formatFloat(amount, {
            digits,
            minDigits: options.minDigits,
            trailingZeros: options.trailingZeros,
        });
    }

    if (!currency || options.noSymbol) {
        return formattedAmount;
    }
    const formatted = [currency.symbol, formattedAmount];
    if (currency.position === "after") {
        formatted.reverse();
    }
    return formatted.join(nbsp);
}
