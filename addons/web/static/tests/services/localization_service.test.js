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
import { localization } from "@web/core/l10n/localization";
import { Settings } from "@web/core/l10n/luxon";
import { IndexedDB } from "@web/core/utils/indexed_db";

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
