// @ts-check
/** @odoo-module native */

/**
 * @param {string | null} locale
 * @returns {string}
 */
export function jsToPyLocale(locale) {
    if (!locale) {
        return "";
    }
    let language, script, region;
    try {
        ({ language, script, region } = new Intl.Locale(locale));
        if (language === "fil") {
            language = "tl";
        }
    } catch {
        return locale;
    }
    let xpgLocale = language;
    if (region) {
        xpgLocale += `_${region}`;
    }
    switch (script) {
        case "Cyrl":
            xpgLocale += "@Cyrl";
            break;
        case "Latn":
            xpgLocale += "@latin";
            break;
    }
    return xpgLocale;
}

/**
 * @param {string} locale
 * @returns {string}
 */
export function pyToJsLocale(locale) {
    if (!locale) {
        return "";
    }
    const regex = /^([a-z]+)(_[A-Z\d]+)?(@.+)?$/;
    const match = locale.match(regex);
    if (!match) {
        return locale;
    }
    const [, language, territory, modifier] = match;
    const subtags = [language];
    switch (modifier) {
        case "@Cyrl":
            subtags.push("Cyrl");
            break;
        case "@latin":
            subtags.push("Latn");
            break;
    }
    if (territory) {
        subtags.push(territory.slice(1));
    }
    return subtags.join("-");
}
