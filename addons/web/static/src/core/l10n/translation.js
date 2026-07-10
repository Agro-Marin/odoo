// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/translation - Runtime i18n: _t() tagged-template translator with markup-safe interpolation */

import { localization } from "@web/core/l10n/localization";
import { formatList } from "@web/core/l10n/utils";
import { isIterable } from "@web/core/utils/collections/arrays";
import { Deferred } from "@web/core/utils/concurrency";
import { htmlSprintf, isMarkup } from "@web/core/utils/dom/html";
import { mapSubstitutions, sprintf } from "@web/core/utils/format/strings";

/** @typedef {any} Markup */

/**
 * Returns true if the given value is a non-empty string, i.e. it contains other
 * characters than white spaces and zero-width spaces.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
function isNotBlank(value) {
    return typeof value === "string" && !R_BLANK.test(value);
}

/**
 * Same behavior as sprintf, but doing two additional things:
 * - If any of the provided values is an iterable, it will format its items
 *   as a language-specific formatted string representing the elements of the
 *   list.
 * - If any of the provided values is a markup, it will escape all non-markup
 *   content before performing the interpolation, then wraps the result in a
 *   markup.
 *
 * @param {string} str
 * @param {Substitutions} substitutions
 * @returns {string | Markup | TranslatedString}
 */
function translationSprintf(str, substitutions) {
    let hasMarkup = false;

    /**
     * @param {string | Markup} value
     * @returns {string | Markup}
     */
    function formatSubstitution(value) {
        hasMarkup ||= isMarkup(value);
        // The `!(value instanceof String)` check is to prevent interpreting `Markup` and `TranslatedString`
        // objects as iterables, since they are both subclasses of `String`.
        if (isIterable(value) && !(value instanceof String)) {
            return formatList(value);
        } else {
            return value;
        }
    }
    const formattedSubstitutions = mapSubstitutions(substitutions, formatSubstitution);
    if (hasMarkup) {
        return htmlSprintf(str, ...formattedSubstitutions);
    } else {
        return sprintf(str, ...formattedSubstitutions);
    }
}

/**
 * @template [T=unknown]
 * @typedef {import("@web/core/utils/format/strings").Substitutions<T>} Substitutions
 */

const DEFAULT_MODULE = "base";
const R_BLANK = /^[\s\u200B]*$/;

/**
 * Translates a term, or returns the term as it is if no translation can be
 * found.
 *
 * Extra positional arguments are inserted in place of %s placeholders.
 *
 * If the first extra argument is an object, the keys of that object are used to
 * map its entries to keyworded placeholders (%(kw_placeholder)s) for
 * replacement.
 *
 * If one or more of the extra arguments are iterables, they will be turned
 * into language-specific formatted strings representing the elements of the
 * list.
 *
 * If at least one of the extra arguments is a markup, the translation and
 * non-markup content are escaped, and the result is wrapped in a markup.
 *
 * @example
 * _t("Good morning"); // "Bonjour"
 * _t("Good morning %s", user.name); // "Bonjour Marc"
 * _t("Good morning %(newcomer)s, goodbye %(departer)s", { newcomer: Marc, departer: Mitchel }); // Bonjour Marc, au revoir Mitchel
 * _t("I love %s", markup`<blink>Minecraft</blink>`); // Markup {"J'adore <blink>Minecraft</blink>"}
 * _t("Good morning %s!", ["Mitchell", "Marc", "Louis"]); // Bonjour Mitchell, Marc et Louis !
 *
 * @param {string} source
 * @param {Substitutions} substitutions
 * @returns {string | Markup | TranslatedString}
 */
export function _t(source, ...substitutions) {
    return appTranslateFn(source, odoo.translationContext, ...substitutions);
}

// ── Plural-aware form selector ───────────────────────────────────────────
// Each form must already be translated (typically via `_t`); `_pl` only picks
// which form to return for `count` per CLDR plural rules — it does NOT
// translate. Real gettext msgid_plural support needs extractor work in
// core/odoo/tools/translate.py (tracked as follow-up); this helper covers the
// common one/other case and falls back to "other" for unprovided categories.

/** @type {Map<string, Intl.PluralRules>} */
const _pluralRulesCache = new Map();

/**
 * Pick the right singular/plural form for `count` under the current
 * locale's CLDR plural rules.
 *
 * Requires `localization.code` to be populated — i.e. must run after
 * `localization_service` has started, the same constraint `_t()` has.
 *
 * @example
 * _pl(count, {
 *   zero: _t("No records"),
 *   one: _t("1 record"),
 *   other: _t("%s records", count),
 * })
 *
 * @template {string | TranslatedString | Markup} T
 * @param {number} count
 * @param {Partial<Record<Intl.LDMLPluralRule, T>> & { other: T }} forms
 *   plural-form map keyed by CLDR category — zero, one, two, few, many, other.
 *   `other` is required as the fallback for any category the caller did
 *   not provide.
 * @returns {T}
 */
export function _pl(count, forms) {
    // ``localization.code`` is the Python-locale form (``en_US``); ``Intl.PluralRules``
    // requires BCP-47 (``en-US``) and throws ``RangeError`` otherwise, which would fail
    // every caller (e.g. formatX2many's "x records" aggregate rows) — hence the conversion.
    const code = localization.code.replace(/_/g, "-");
    let rules = _pluralRulesCache.get(code);
    if (!rules) {
        rules = new Intl.PluralRules(code);
        _pluralRulesCache.set(code, rules);
    }
    const category = rules.select(count);
    return forms[category] ?? forms.other;
}

/**
 * Wrapper for _t that the transpiler injects to attach the calling module's
 * context — avoids conflicting translations for the same term across
 * modules (e.g. "table": restaurant vs. spreadsheet).
 *
 * @param {string} source The term to translate
 * @param {string} [moduleName] The name of the module, used as a context key to
 * retrieve the translation.
 * @param  {Substitutions} substitutions The other arguments passed to _t.
 * @returns {string | Markup | TranslatedString}
 */
export function appTranslateFn(source, moduleName, ...substitutions) {
    if (translatedTerms[translationLoaded]) {
        // Fast path once translations are loaded: behaviorally identical to
        // `new TranslatedString(...).valueOf()` (which is what the slow path
        // reduces to when not lazy), without allocating and discarding the
        // TranslatedString wrapper on every call.
        if (!isNotBlank(source)) {
            // Matches the constructor's `new String(value)` escape hatch,
            // whose `.valueOf()` returns the coerced primitive.
            return String(source);
        }
        const context = moduleName || DEFAULT_MODULE;
        const translation =
            translatedTerms[context]?.[source] ??
            translatedTermsGlobal[source] ??
            source;
        return substitutions.length
            ? translationSprintf(translation, substitutions)
            : translation;
    }
    const string = new TranslatedString(source, substitutions, moduleName);
    return string.lazy ? string : string.valueOf();
}

/**
 * Load the installed languages long names and code
 *
 * The result of the call is put in cache.
 * If any new language is installed, a full page refresh will happen,
 * so there is no need invalidate it.
 *
 * @param {import("services").ServiceFactories["orm"]} orm
 */
export async function loadLanguages(orm) {
    if (!loadLanguages.installedLanguages) {
        loadLanguages.installedLanguages = await orm.call("res.lang", "get_installed");
    }
    return loadLanguages.installedLanguages;
}
/** @type {any[] | null} Cached result — patchable by test helpers. */
loadLanguages.installedLanguages = null;

export class TranslatedString extends String {
    /** @type {string} */
    context;
    lazy = false;
    /** @type {Substitutions} */
    substitutions;

    /**
     *
     * @param {string} value
     * @param {Substitutions} substitutions
     * @param {string | null} [context]
     */
    constructor(value, substitutions, context) {
        super(value);

        if (!isNotBlank(value)) {
            // @ts-expect-error — valid JS: constructor returning plain String to skip translation
            return new String(value);
        }

        this.lazy = !translatedTerms[translationLoaded];
        this.substitutions = substitutions;
        this.context = context || DEFAULT_MODULE;
    }

    /** @returns {string} */
    toString() {
        return this.valueOf();
    }

    /** @returns {string} Ensure JSON.stringify uses the translated value, not the source. */
    toJSON() {
        return this.valueOf();
    }

    /** @returns {string} */
    valueOf() {
        const source = super.valueOf();
        if (this.lazy && !translatedTerms[translationLoaded]) {
            // Evaluate lazy translated string while translations are not loaded
            // -> error
            throw new Error(
                `Cannot translate string: translations have not been loaded`,
            );
        }
        const translation =
            translatedTerms[this.context]?.[source] ??
            translatedTermsGlobal[source] ??
            source;
        if (this.substitutions.length) {
            return translationSprintf(translation, this.substitutions);
        } else {
            return translation;
        }
    }
}

// ── Cross-bundle singleton state ─────────────────────────────────────────
// Native ESM gives each bundle (e.g. ``web.assets_web`` vs. the
// ``web.assets_tests`` satellite loaded whenever ``--test-enable`` is on) its
// own copy of this module's top-level bindings. Without routing through
// ``globalThis``, the ``localization`` service flips ``translatedTerms`` /
// resolves ``translationIsReady`` only in the parent bundle's copy, leaving
// the satellite's copy permanently "not loaded" — so ``_t(...)`` calls in
// satellite-bundled tour ``steps()`` throw and fail tests that pass on
// upstream's amd-style loader. ``Symbol.for(...)`` is the matching trick for
// the lookup key itself: it resolves to the same symbol across realms/bundles.

/** @type {symbol} */
export const translationLoaded = Symbol.for("@web/core/l10n/translationLoaded");

const _STATE_KEY = "__odoo_l10n_state__";
/** @type {{ translatedTerms: Record<string | symbol, any>, translatedTermsGlobal: Record<string, string>, translationIsReady: Deferred }} */
const _state = /** @type {any} */ (
    globalThis[_STATE_KEY] ??= {
        translatedTerms: { [translationLoaded]: false },
        translatedTermsGlobal: Object.create(null),
        translationIsReady: new Deferred(),
    }
);

/** @type {Record<string | symbol, any>} */
export const translatedTerms = _state.translatedTerms;
/**
 * Contains all the translated terms. Unlike "translatedTerms", there is no
 * "namespacing" by module. It is used as a fallback when no translation is
 * found within the module's context, or when the context is not known.
 */
/** @type {Record<string, string>} */
export const translatedTermsGlobal = _state.translatedTermsGlobal;
/** @type {Deferred} */
export const translationIsReady = _state.translationIsReady;
