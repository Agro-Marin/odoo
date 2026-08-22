// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { jsToPyLocale, pyToJsLocale } from "@web/core/l10n/utils/locales";

describe.current.tags("headless");

describe("pyToJsLocale", () => {
    test("language and territory", () => {
        expect(pyToJsLocale("en")).toBe("en");
        expect(pyToJsLocale("fr_BE")).toBe("fr-BE");
        expect(pyToJsLocale("en_US")).toBe("en-US");
        expect(pyToJsLocale("zh_CN")).toBe("zh-CN");
    });

    test("script modifiers become subtags in the right position", () => {
        expect(pyToJsLocale("sr@latin")).toBe("sr-Latn");
        expect(pyToJsLocale("sr@Cyrl")).toBe("sr-Cyrl");
        expect(pyToJsLocale("uz@Cyrl")).toBe("uz-Cyrl");
    });

    test("an empty or unparseable code is handed back unchanged", () => {
        expect(pyToJsLocale("")).toBe("");
        expect(pyToJsLocale("garbage!")).toBe("garbage!");
    });

    test("a non-script modifier is dropped", () => {
        expect(pyToJsLocale("fr_BE@euro")).toBe("fr-BE");
        expect(pyToJsLocale("ca_ES@valencia")).toBe("ca-ES");
    });
});

describe("jsToPyLocale", () => {
    test("language and region", () => {
        expect(jsToPyLocale("en")).toBe("en");
        expect(jsToPyLocale("fr-BE")).toBe("fr_BE");
    });

    test("scripts become the modifier spelling glibc uses", () => {
        expect(jsToPyLocale("sr-Latn")).toBe("sr@latin");
        expect(jsToPyLocale("sr-Cyrl")).toBe("sr@Cyrl");
    });

    test("Filipino is normalised to the Tagalog code Odoo ships", () => {
        expect(jsToPyLocale("fil")).toBe("tl");
        expect(jsToPyLocale("fil-PH")).toBe("tl_PH");
    });

    test("nullish and unparseable input do not throw", () => {
        expect(jsToPyLocale("")).toBe("");
        expect(jsToPyLocale(null)).toBe("");
        expect(jsToPyLocale("!!bad!!")).toBe("!!bad!!");
    });
});

describe("round trip", () => {
    test("every language base ships survives py -> js -> py", () => {
        for (const code of ["en", "fr_BE", "zh_CN", "sr@latin", "sr@Cyrl", "es_MX"]) {
            expect(jsToPyLocale(pyToJsLocale(code))).toBe(code, { message: code });
        }
    });
});
