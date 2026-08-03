// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    makeMockEnv,
    onRpc,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { localization } from "@web/core/l10n/localization";
import { applyLuxonLocale } from "@web/core/l10n/localization_service";
import { Settings } from "@web/core/l10n/luxon";
import { IndexedDB } from "@web/core/utils/indexed_db";
import { session } from "@web/session";

describe.current.tags("headless");

const LANG_PARAMETERS = {
    date_format: "%m/%d/%Y",
    time_format: "%H:%M:%S",
    decimal_point: ",",
    direction: "ltr",
    grouping: "[3,0]",
    thousands_sep: ".",
    week_start: 1,
};

/**
 * @param {Partial<{ hash: string, messages: { id: string, string: string }[] }>} [options]
 */
function makeTranslationsResult({ hash = "hash1", messages = [] } = {}) {
    return {
        lang: "en",
        lang_parameters: LANG_PARAMETERS,
        modules: { web: { messages } },
        multi_lang: false,
        hash,
    };
}

/**
 * @param {{ read?: () => any, write?: (table: string, key: string, value: any) => any }} [impl]
 */
function mockLocalizationDB({
    read = async () => undefined,
    // `async`, like the real `IndexedDB.write`. A stub returning `undefined`
    // silently narrows the contract: callers that chain off the write (to know
    // when it actually landed) blow up only in tests.
    write = async () => {},
} = {}) {
    patchWithCleanup(IndexedDB.prototype, { read, write });
}

test("cold boot: the parse-time preload is adopted, not refetched", async () => {
    mockLocalizationDB();
    onRpc("/web/webclient/translations", () => {
        expect.step("unexpected service fetch");
    });
    const preloadedResult = makeTranslationsResult({
        messages: [{ id: "Hello", string: "Bonjour (preloaded)" }],
    });
    /** @type {any} */ (odoo).loadTranslationsURL =
        "/web/webclient/translations?hash=&lang=en";
    /** @type {any} */ (odoo).loadTranslationsPromise = Promise.resolve(
        new Response(JSON.stringify(preloadedResult)),
    );
    await makeMockEnv();
    expect(/** @type {any} */ (odoo).loadTranslationsPromise).toBe(null);
    expect(/** @type {any} */ (odoo).loadTranslationsURL).toBe(null);
    expect(localization.decimalPoint).toBe(",");
    expect.verifySteps([]);
});

test("warm boot: a stale preload is discarded and the cached hash revalidated", async () => {
    mockLocalizationDB({
        read: () => makeTranslationsResult({ hash: "cached-hash" }),
    });
    onRpc("/web/webclient/translations", (request) => {
        expect.step(`fetch hash=${new URL(request.url).searchParams.get("hash")}`);
        return makeTranslationsResult({ hash: "cached-hash" });
    });
    /** @type {any} */ (odoo).loadTranslationsURL =
        "/web/webclient/translations?hash=&lang=en";
    /** @type {any} */ (odoo).loadTranslationsPromise = Promise.resolve(
        new Response(JSON.stringify({})),
    );
    await makeMockEnv();
    expect(/** @type {any} */ (odoo).loadTranslationsPromise).toBe(null);
    expect.verifySteps(["fetch hash=cached-hash"]);
});

test("warm boot: a failing background refresh only warns", async () => {
    mockLocalizationDB({
        read: () => makeTranslationsResult({ hash: "cached-hash" }),
    });
    patchWithCleanup(console, {
        warn: () => expect.step("console.warn"),
    });
    onRpc("/web/webclient/translations", () => {
        expect.step("translations fetch");
        throw new Error("Connection refused");
    });
    await makeMockEnv();
    expect(localization.decimalPoint).toBe(",");
    expect(localization.weekStart).toBe(1);
    await animationFrame();
    expect.verifySteps(["translations fetch", "console.warn"]);
});

test("cold boot: fetch failure falls back to usable localization defaults", async () => {
    mockLocalizationDB();
    patchWithCleanup(console, {
        error: () => expect.step("console.error"),
    });
    onRpc("/web/webclient/translations", () => {
        expect.step("translations fetch");
        throw new Error("Connection refused");
    });
    await makeMockEnv();
    expect.verifySteps(["translations fetch", "console.error"]);
    expect(localization.dateFormat).toBe("MM/dd/yyyy");
    expect(localization.decimalPoint).toBe(".");
    expect(localization.grouping).toEqual([3, 0]);
});

test("fetch lang, Luxon locale, and localization.code share one source", async () => {
    mockLocalizationDB();
    serverState.lang = null;
    document.documentElement.setAttribute("lang", "fr-FR");
    after(() => document.documentElement.removeAttribute("lang"));
    onRpc("/web/webclient/translations", (request) => {
        expect.step(`fetch lang=${new URL(request.url).searchParams.get("lang")}`);
        return makeTranslationsResult();
    });
    await makeMockEnv();
    expect.verifySteps(["fetch lang=fr_FR"]);
    expect(localization.code).toBe("fr_FR");
    expect(Settings.defaultLocale).toBe("fr-FR");
});

test("the localStorage cache marker is set only after the IndexedDB write lands", async () => {
    // The marker tells the parse-time preload script in `web.webclient_bootstrap`
    // that IndexedDB holds these translations, so it skips its early fetch.
    // Setting it beside a fire-and-forget write can leave marker-present +
    // IndexedDB-empty, and the next cold boot then pays a fully serialized
    // translation fetch — the exact cost the cache exists to avoid.
    browser.localStorage.removeItem("webclient_translations_version");
    /** @type {string[]} */
    const order = [];
    /** @type {any} */
    let releaseWrite;
    const writeLanded = new Promise((resolve) => {
        releaseWrite = resolve;
    });
    mockLocalizationDB({
        read: async () => undefined,
        write: async () => {
            order.push("write:start");
            await writeLanded;
            order.push("write:done");
        },
    });
    onRpc("/web/webclient/translations", () => makeTranslationsResult({ hash: "h1" }));

    await makeMockEnv();
    expect(browser.localStorage.getItem("webclient_translations_version")).toBe(null);
    expect(order).toEqual(["write:start"]);

    releaseWrite();
    await Promise.resolve();
    await Promise.resolve();
    expect(order).toEqual(["write:start", "write:done"]);
    expect(browser.localStorage.getItem("webclient_translations_version")).not.toBe(
        null,
    );
});

test("applyLuxonLocale moves the locale and its numbering system together", () => {
    // luxon takes the digits from `defaultNumberingSystem` and everything else
    // from `defaultLocale`: a caller that re-points one without the other — as
    // the public boot did when overriding the session language with the
    // frontend one — renders an English page's dates in Arabic-Indic digits.
    patchWithCleanup(Settings, {
        defaultLocale: "ar-001",
        defaultNumberingSystem: "arab",
    });
    applyLuxonLocale("fr-BE");
    expect(Settings.defaultLocale).toBe("fr-BE");
    expect(Settings.defaultNumberingSystem).toBe("latn");

    applyLuxonLocale("ar-SA");
    expect(Settings.defaultLocale).toBe("ar-SA");
    expect(Settings.defaultNumberingSystem).toBe("arab");
});

/**
 * Pins the language the service resolves, by intercepting the request it makes.
 *
 * @param {{ isFrontend?: boolean, cookieLang?: string, htmlLang?: string }} setup
 * @returns {Promise<void>}
 */
async function bootWith({ isFrontend, cookieLang, htmlLang }) {
    mockLocalizationDB();
    patchWithCleanup(session, { is_frontend: isFrontend });
    // the browser language is deliberately one that is neither the cookie's nor
    // the <html lang>'s, and whose numbering system is not latn
    patchWithCleanup(browser, {
        navigator: { ...browser.navigator, language: "ar-SA" },
    });
    patchWithCleanup(Settings, { defaultLocale: "xx", defaultNumberingSystem: "xx" });
    if (cookieLang) {
        cookie.set("frontend_lang", cookieLang);
        after(() => cookie.delete("frontend_lang"));
    }
    const html = document.documentElement;
    const previousLang = html.getAttribute("lang");
    html.removeAttribute("lang");
    if (htmlLang) {
        html.setAttribute("lang", htmlLang);
    }
    after(() => {
        html.removeAttribute("lang");
        if (previousLang !== null) {
            html.setAttribute("lang", previousLang);
        }
    });
    onRpc("/web/webclient/translations", (request) => {
        expect.step(`lang=${new URL(request.url).searchParams.get("lang")}`);
        return makeTranslationsResult({ hash: "h" });
    });
    await makeMockEnv();
}

describe("the language a page is rendered in", () => {
    test("a frontend page follows the frontend_lang cookie, not the browser", async () => {
        await bootWith({ isFrontend: true, cookieLang: "en_US" });
        // used to fall through to navigator.language on the login/portal pages,
        // which render no <html lang> and carry no user_context: an English page
        // fetched — and cached under — the visitor's browser language
        expect.verifySteps(["lang=en_US"]);
        expect(localization.code).toBe("en_US");
        expect(Settings.defaultLocale).toBe("en-US");
        expect(Settings.defaultNumberingSystem).toBe("latn");
    });

    test("a frontend page without a cookie falls back to <html lang>", async () => {
        await bootWith({ isFrontend: true, htmlLang: "fr-BE" });
        expect.verifySteps(["lang=fr_BE"]);
        expect(Settings.defaultLocale).toBe("fr-BE");
    });

    test("a frontend page with neither falls back to en-US, never the browser", async () => {
        await bootWith({ isFrontend: true });
        expect.verifySteps(["lang=en_US"]);
        expect(Settings.defaultLocale).toBe("en-US");
        expect(Settings.defaultNumberingSystem).toBe("latn");
    });

    test("the backend ignores the frontend_lang cookie", async () => {
        // the cookie is set on the same host by any frontend visit; the backend
        // must keep following the session user's language
        await bootWith({ isFrontend: false, cookieLang: "fr_FR" });
        expect.verifySteps(["lang=en"]);
    });
});
