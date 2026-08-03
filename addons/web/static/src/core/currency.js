// @ts-check
/** @odoo-module native */

/** @module @web/core/currency */

import { reactive } from "@odoo/owl";
import { UserEvent } from "@web/core/events";
import { parseDate } from "@web/core/l10n/dates";
import { rpc } from "@web/core/network/rpc";
import { user, userBus } from "@web/core/user";
import { formatFloat, humanNumber } from "@web/core/utils/format/numbers";
import { nbsp } from "@web/core/utils/format/strings";
import { session } from "@web/session";

/** @type {Record<number, {symbol: string, position: string, digits: [number, number]}>} */
export const currencies = session.currencies || {};
delete session.currencies;

/**
 * @param {number} id
 * @returns {{symbol: string, position: string, digits: [number, number]} | undefined}
 */
export function getCurrency(id) {
    return currencies[id];
}

/**
 * @type {Record<number, {rate: number, date: import("@web/core/l10n/dates").NullableDateTime}>}
 */
const rates = reactive({});
/**
 * @type {Promise<void> | null}
 */
let ratesPromise = null;
let ratesEpoch = 0;

/**
 * @param {Array<{id: number, inverse_rate: number, date: string}>} records
 */
function applyRates(records) {
    const newRates = Object.fromEntries(
        records.map((r) => [
            r.id,
            {
                // `res.currency.inverse_rate` = units of the COMPANY currency
                // per 1 unit of this currency, i.e. the multiplier that takes
                // an amount INTO the company currency.
                toCompanyRate: r.inverse_rate,
                date: parseDate(r.date),
            },
        ]),
    );
    for (const id of Object.keys(rates)) {
        if (!(id in newRates)) {
            delete rates[Number(id)];
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

userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, () => {
    ratesEpoch++;
    ratesPromise = null;
});

/**
 * @returns {Promise<Record<number, {rate: number, date: import("@web/core/l10n/dates").NullableDateTime}>>}
 */
export async function getCurrencyRates() {
    if (!ratesPromise) {
        const prom = fetchCurrencyRates().finally(() => {
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
 * @param {number} amount
 * @param {number} [currencyId]
 * @param {any} [options]
 * @returns {string}
 */
export function formatCurrency(amount, currencyId, options = {}) {
    const currency = getCurrency(/** @type {number} */ (currencyId));

    const digits = options.digits !== undefined ? options.digits : currency?.digits;

    let formattedAmount;
    if (options.humanReadable) {
        formattedAmount = humanNumber(amount, {
            decimals: digits ? digits[1] : 2,
            minIntegerDigits: options.minIntegerDigits,
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
