// @ts-check
/** @odoo-module native */

/** @module @web/services/localization_service - Fetches translations and configures Luxon locale, numbering system, and date/number formats */

import { browser } from "@web/core/browser/browser";
import { strftimeToLuxonFormat } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { Settings } from "@web/core/l10n/luxon";
import {
    translatedTerms,
    translatedTermsGlobal,
    translationIsReady,
    translationLoaded,
} from "@web/core/l10n/translation";
import { jsToPyLocale } from "@web/core/l10n/utils";
import { registry } from "@web/core/registry";
import { l10nLog } from "@web/core/utils/asset_log";
import { IndexedDB } from "@web/core/utils/indexed_db";
import { objectToUrlEncodedString } from "@web/core/utils/urls";
import { user } from "@web/services/user";
import { session } from "@web/session";

/** @type {[RegExp, string][]} */
const NUMBERING_SYSTEMS = [
    [/^ar-(sa|sy|001)$/i, "arab"],
    [/^bn/i, "beng"],
    [/^bo/i, "tibt"],
    [/^pa-in/i, "guru"],
    [/^ta/i, "tamldec"],
    [/.*/i, "latn"],
];

/**
 * Last-resort `lang_parameters` (en-US-like) applied when the very first
 * translation fetch fails with nothing cached: without them `localization`
 * stays empty and every date/number formatter on the page throws or renders
 * garbage. Terms remain untranslated (English source strings).
 */
const FALLBACK_LANG_PARAMETERS = {
    date_format: "%m/%d/%Y",
    time_format: "%H:%M:%S",
    decimal_point: ".",
    direction: "ltr",
    grouping: "[3,0]",
    thousands_sep: ",",
    week_start: 7,
};

/**
 * Service that fetches translations from the server and configures the Luxon
 * locale, numbering system, and Odoo localization settings (date/time formats,
 * decimal point, thousands separator, etc.).
 *
 * Uses IndexedDB for caching translations across page loads.
 */
export const localizationService = {
    /** @returns {Promise<typeof import("@web/core/l10n/localization").localization>} */
    start: async () => {
        const localizationDB = new IndexedDB("localization", session.registry_hash);
        const translationURL = session.translationURL || "/web/webclient/translations";
        const locale =
            user.lang ||
            document.documentElement.getAttribute("lang") ||
            browser.navigator.language;
        const lang = jsToPyLocale(locale);

        /**
         * Synchronous localStorage mirror of the (asynchronous) IndexedDB
         * translations cache, consumed by the parse-time preload script in
         * `web.webclient_bootstrap` (webclient_templates.xml). The inline
         * script cannot await an IndexedDB read, so it checks this marker
         * instead: when it equals `${registry_hash}/${lang}` the IndexedDB
         * read will (almost certainly) hit and no early fetch is started;
         * otherwise (first visit, deploy that bumped registry_hash, language
         * change) the fetch starts at parse time and is adopted below.
         * A stale/lost marker is always safe: it only costs one redundant
         * prefetch (marker stale) or a later fetch (marker lost with IDB
         * intact — same as before this optimization).
         */
        const translationsCacheMarker = `${session.registry_hash}/${lang}`;
        const markTranslationsCached = () => {
            try {
                browser.localStorage.setItem(
                    "webclient_translations_version",
                    translationsCacheMarker,
                );
            } catch {
                // localStorage unavailable/full: only disables the cold-boot
                // preload optimization, never breaks translations.
            }
        };

        /**
         * Fetch translations from the server. If the hash matches the cached
         * version, no update is performed.
         * @param {string | undefined} hash - hash of the currently cached translations
         */
        const fetchTranslations = async (hash) => {
            let queryString = objectToUrlEncodedString({ hash, lang });
            queryString = queryString.length ? `?${queryString}` : queryString;
            const url = `${translationURL}${queryString}`;
            const preload = /** @type {any} */ (odoo);
            let responsePromise;
            if (
                !hash &&
                preload.loadTranslationsPromise &&
                preload.loadTranslationsURL === url
            ) {
                l10nLog("fetch", "fetchTranslations adopting preload", `url=${url}`);
                responsePromise = preload.loadTranslationsPromise;
            } else {
                if (preload.loadTranslationsPromise) {
                    preload.loadTranslationsPromise.then(
                        (/** @type {Response} */ res) => res.body?.cancel(),
                        () => {},
                    );
                }
                l10nLog("fetch", "fetchTranslations begin", `url=${url}`);
                responsePromise = browser.fetch(url, {
                    cache: "no-store",
                });
            }
            preload.loadTranslationsPromise = null;
            preload.loadTranslationsURL = null;
            const response = await responsePromise;
            l10nLog(
                "fetch",
                "fetchTranslations response",
                `status=${response.status}`,
                `ok=${response.ok}`,
            );
            if (!response.ok) {
                throw new Error("Error while fetching translations");
            }
            const result = await response.json();
            if (result.hash !== hash) {
                // Apply first (nothing below blocks the UI on storage), then
                // mark ONLY once the IndexedDB write has actually landed. The
                // marker used to be set next to a fire-and-forget write, which
                // can produce the one combination the marker contract does not
                // cover: marker present, IndexedDB empty. The parse-time preload
                // script in `web.webclient_bootstrap` then trusts the marker and
                // skips its early fetch, so the next cold boot pays a fully
                // serialized translation fetch — the exact cost this cache
                // exists to avoid.
                updateTranslations(result);
                localizationDB
                    .write(translationURL, JSON.stringify({ lang }), result)
                    .then(markTranslationsCached, () => {
                        // Storage unavailable/full: leave the marker unset so the
                        // next boot prefetches instead of trusting a phantom cache.
                    });
                l10nLog(
                    "fetch",
                    "fetchTranslations cached + applied",
                    `hash=${result.hash}`,
                );
            }
        };

        /**
         * Apply translation data to the global `translatedTerms` and configure
         * the `localization` object with date/time formats and number settings.
         * @param {{
         *     hash: string,
         *     modules: Record<string, { messages: { id: string, string: string }[] }>,
         *     lang_parameters: {
         *         date_format: string,
         *         time_format: string,
         *         decimal_point: string,
         *         direction: string,
         *         grouping: string,
         *         thousands_sep: string,
         *         week_start: number,
         *     },
         *     multi_lang: boolean,
         * }} result
         */
        const updateTranslations = (result) => {
            /** @type {Record<string, Record<string, string>>} */
            const terms = {};
            for (const addon of Object.keys(result.modules)) {
                terms[addon] = {};
                for (const message of result.modules[addon].messages) {
                    terms[addon][message.id] = message.string;
                    translatedTermsGlobal[message.id] = message.string;
                }
            }
            Object.assign(translatedTerms, terms);

            const userLocalization = result.lang_parameters;
            const dateFormat = strftimeToLuxonFormat(userLocalization.date_format);
            const timeFormat = strftimeToLuxonFormat(userLocalization.time_format);

            Object.assign(localization, {
                dateFormat,
                timeFormat,
                dateTimeFormat: `${dateFormat} ${timeFormat}`,
                decimalPoint: userLocalization.decimal_point,
                direction: userLocalization.direction,
                grouping: (() => {
                    try {
                        return JSON.parse(userLocalization.grouping);
                    } catch {
                        return [3, 0];
                    }
                })(),
                multiLang: result.multi_lang,
                thousandsSep: userLocalization.thousands_sep,
                weekStart: userLocalization.week_start,
            });
        };

        const storedTranslations = await localizationDB.read(
            translationURL,
            JSON.stringify({ lang }),
        );
        l10nLog(
            "cache",
            "storedTranslations",
            `hit=${Boolean(storedTranslations)}`,
            `hash=${storedTranslations?.hash}`,
            `lang=${lang}`,
        );

        const translationProm = fetchTranslations(storedTranslations?.hash);
        if (storedTranslations) {
            translationProm.catch((e) =>
                console.warn("Background translation fetch failed:", e),
            );
            markTranslationsCached();
            updateTranslations(storedTranslations);
        } else {
            l10nLog("cache", "no cache, awaiting fetch");
            try {
                await translationProm;
            } catch (e) {
                console.error(
                    "Translation fetch failed on cold boot; falling back to default localization parameters:",
                    e,
                );
                updateTranslations({
                    hash: "",
                    modules: {},
                    lang_parameters: FALLBACK_LANG_PARAMETERS,
                    multi_lang: false,
                });
            }
        }

        translatedTerms[translationLoaded] = true;
        translationIsReady.resolve(true);

        Settings.defaultLocale = locale;
        for (const [re, numberingSystem] of NUMBERING_SYSTEMS) {
            if (re.test(locale)) {
                Settings.defaultNumberingSystem = numberingSystem;
                break;
            }
        }
        localization.code = lang;
        return localization;
    },
};

registry.category("services").add("localization", localizationService);
