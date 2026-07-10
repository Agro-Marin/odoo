// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";
import { _t as basic_t } from "@web/core/l10n/translation";
import {
    capitalize,
    escape,
    escapeRegExp,
    exprToBoolean,
    hashCode,
    intersperse,
    isEmail,
    isNumeric,
    sprintf,
    uuid,
} from "@web/core/utils/format/strings";

function _t() {
    odoo.translationContext = "web";
    const translatedTerm = basic_t(...arguments);
    odoo.translationContext = null;
    return translatedTerm;
}

describe.current.tags("headless");

test("escape", () => {
    expect(escape("<a>this is a link</a>")).toBe("&lt;a&gt;this is a link&lt;/a&gt;");
    expect(escape(`<a href="https://www.odoo.com">odoo<a>`)).toBe(
        `&lt;a href=&quot;https://www.odoo.com&quot;&gt;odoo&lt;a&gt;`,
    );
    expect(escape(`<a href='https://www.odoo.com'>odoo<a>`)).toBe(
        `&lt;a href=&#x27;https://www.odoo.com&#x27;&gt;odoo&lt;a&gt;`,
    );
    expect(escape("<a href='https://www.odoo.com'>Odoo`s website<a>")).toBe(
        `&lt;a href=&#x27;https://www.odoo.com&#x27;&gt;Odoo&#x60;s website&lt;a&gt;`,
    );
});

test("escapeRegExp", () => {
    expect(escapeRegExp("")).toBe("");
    expect(escapeRegExp("wowl")).toBe("wowl");
    expect(escapeRegExp("[wowl]")).toBe("\\[wowl\\]");
    expect(escapeRegExp("[wowl.odoo]")).toBe("\\[wowl\\.odoo\\]");
    expect(escapeRegExp("^odoo.define([.]*)$")).toBe(
        "\\^odoo\\.define\\(\\[\\.\\]\\*\\)\\$",
    );
    expect(escapeRegExp("[.*+?^${}()|[]\\")).toBe(
        "\\[\\.\\*\\+\\?\\^\\$\\{\\}\\(\\)\\|\\[\\]\\\\",
    );
});

test("intersperse", () => {
    expect(intersperse("", [])).toBe("");
    expect(intersperse("0", [])).toBe("0");
    expect(intersperse("012", [])).toBe("012");
    expect(intersperse("1", [])).toBe("1");
    expect(intersperse("12", [])).toBe("12");
    expect(intersperse("123", [])).toBe("123");
    expect(intersperse("1234", [])).toBe("1234");
    expect(intersperse("123456789", [])).toBe("123456789");
    expect(intersperse("&ab%#@1", [])).toBe("&ab%#@1");
    expect(intersperse("0", [])).toBe("0");
    expect(intersperse("0", [1])).toBe("0");
    expect(intersperse("0", [2])).toBe("0");
    expect(intersperse("0", [200])).toBe("0");
    expect(intersperse("12345678", [0], ".")).toBe("12345678");
    expect(intersperse("", [1], ".")).toBe("");
    expect(intersperse("12345678", [1], ".")).toBe("1234567.8");
    expect(intersperse("12345678", [1], ".")).toBe("1234567.8");
    expect(intersperse("12345678", [2], ".")).toBe("123456.78");
    expect(intersperse("12345678", [2, 1], ".")).toBe("12345.6.78");
    expect(intersperse("12345678", [2, 0], ".")).toBe("12.34.56.78");
    expect(intersperse("12345678", [-1, 2], ".")).toBe("12345678");
    expect(intersperse("12345678", [2, -1], ".")).toBe("123456.78");
    expect(intersperse("12345678", [2, 0, 1], ".")).toBe("12.34.56.78");
    expect(intersperse("12345678", [2, 0, 0], ".")).toBe("12.34.56.78");
    expect(intersperse("12345678", [2, 0, -1], ".")).toBe("12.34.56.78");
    expect(intersperse("12345678", [3, 3, 3, 3], ".")).toBe("12.345.678");
    expect(intersperse("12345678", [3, 0], ".")).toBe("12.345.678");
});

describe("sprintf", () => {
    test("properly formats strings", () => {
        expect(sprintf("Hello %s!", "ged")).toBe("Hello ged!");
        expect(sprintf("Hello %s and %s!", "ged", "lpe")).toBe("Hello ged and lpe!");
        expect(sprintf("Hello %(x)s!", { x: "ged" })).toBe("Hello ged!");
        expect(sprintf("Hello %(x)s and %(y)s!", { x: "ged", y: "lpe" })).toBe(
            "Hello ged and lpe!",
        );
        expect(sprintf("Hello!")).toBe("Hello!");
        expect(sprintf("Hello %s!")).toBe("Hello %s!");
        expect(sprintf("Hello %(value)s!")).toBe("Hello %(value)s!");
        expect(sprintf("Hello %(value)s!", {})).toBe("Hello !");
    });

    test("properly formats numbers", () => {
        expect(sprintf("Hello %s!", 5)).toBe("Hello 5!");
        expect(sprintf("Hello %s and %s!", 9, 10)).toBe("Hello 9 and 10!");
        expect(sprintf("Hello %(x)s!", { x: 11 })).toBe("Hello 11!");
        expect(sprintf("Hello %(x)s and %(y)s!", { x: 12, y: 13 })).toBe(
            "Hello 12 and 13!",
        );
    });

    test("set behavior when value is an Array", () => {
        expect(sprintf("Hello %s!", ["inarray"])).toBe("Hello inarray!");
        expect(sprintf("Hello %s and %s!", [9, "10"], [11])).toBe("Hello 9,10 and 11!");
        expect(sprintf("Hello %(x)s!", { x: [11] })).toBe("Hello 11!");
        expect(sprintf("Hello %(x)s and %(y)s!", { x: [12], y: ["13"] })).toBe(
            "Hello 12 and 13!",
        );
    });

    test("supports lazy translated string", () => {
        patchTranslations({ web: { one: "en", two: "två" } });
        expect(sprintf("Hello %s", _t("one"))).toBe("Hello en");
        expect(sprintf("Hello %s %s", _t("one"), _t("two"))).toBe("Hello en två");

        const vals = { one: _t("one"), two: _t("two") };
        expect(sprintf("Hello %(two)s %(one)s", vals)).toBe("Hello två en");
    });

    test("supports escaped '%' signs", () => {
        expect(sprintf("Escape %s", "%s")).toBe("Escape %s");
        expect(sprintf("Escape %%s", "this!")).toBe("Escape %s");
        expect(sprintf("Escape %%%s", "this!")).toBe("Escape %this!");
        expect(sprintf("Escape %%%%s!", "this")).toBe("Escape %%s!");
        expect(sprintf("Escape %s%s", "this!")).toBe("Escape this!");
        expect(sprintf("Escape %%s%s", "this!")).toBe("Escape %sthis!");
        expect(sprintf("Escape %foo!", "this")).toBe("Escape %foo!");
    });
});

test("capitalize", () => {
    expect(capitalize("abc def")).toBe("Abc def");
    expect(capitalize("Abc def")).toBe("Abc def");
});

test("isEmail", () => {
    expect(isEmail("")).toBe(false);
    expect(isEmail("test")).toBe(false);
    expect(isEmail("test@odoo")).toBe(false);
    expect(isEmail("test@odoo@odoo.com")).toBe(false);
    expect(isEmail("te st@odoo.com")).toBe(false);

    expect(isEmail("test@odoo.com")).toBe(true);
});

test("isNumeric", () => {
    expect(isNumeric("")).toBe(false);
    expect(isNumeric("test1234")).toBe(false);
    expect(isNumeric("1234test")).toBe(false);
    expect(isNumeric("1234test1234")).toBe(false);
    expect(isNumeric("-1234")).toBe(false);
    expect(isNumeric("12,34")).toBe(false);
    expect(isNumeric("12.34")).toBe(false);

    expect(isNumeric("1234")).toBe(true);
});

describe("hashCode", () => {
    test("produces consistent results", () => {
        const h1 = hashCode("hello");
        const h2 = hashCode("hello");
        expect(h1).toBe(h2);
    });

    test("returns 8-character hex string", () => {
        const h = hashCode("test");
        expect(h).toMatch(/^[0-9a-f]{8}$/);
    });

    test("different inputs produce different hashes", () => {
        expect(hashCode("abc")).not.toBe(hashCode("def"));
    });

    test("multiple arguments are joined", () => {
        const combined = hashCode("a", "b");
        expect(combined).not.toBe(hashCode("a"));
        expect(combined).not.toBe(hashCode("b"));
        expect(combined).toBe(hashCode("a", "b"));
    });

    test("empty string produces valid hash", () => {
        expect(hashCode("")).toMatch(/^[0-9a-f]{8}$/);
    });
});

describe("uuid", () => {
    test("returns 16-character hex string", () => {
        const id = uuid();
        expect(id).toMatch(/^[0-9a-f]{16}$/);
    });

    test("generates unique values", () => {
        const ids = new Set(Array.from({ length: 100 }, () => uuid()));
        expect(ids.size).toBe(100);
    });
});

describe("exprToBoolean", () => {
    test("falsy strings return false", () => {
        expect(exprToBoolean("false")).toBe(false);
        expect(exprToBoolean("False")).toBe(false);
        expect(exprToBoolean("0")).toBe(false);
    });

    test("truthy strings return true", () => {
        expect(exprToBoolean("true")).toBe(true);
        expect(exprToBoolean("1")).toBe(true);
        expect(exprToBoolean("anything")).toBe(true);
    });

    test("only the exact strings 'false'/'0' are falsy", () => {
        // Regression: an unanchored alternation (/^false|0$/) treated any
        // string ending in "0" (or starting with "false") as falsy.
        expect(exprToBoolean("10")).toBe(true);
        expect(exprToBoolean("100")).toBe(true);
        expect(exprToBoolean("20")).toBe(true);
        expect(exprToBoolean("false positive")).toBe(true);
        expect(exprToBoolean("0")).toBe(false);
        expect(exprToBoolean("false")).toBe(false);
    });

    test("empty string with trueIfEmpty=false returns false", () => {
        expect(exprToBoolean("")).toBe(false);
    });

    test("empty string with trueIfEmpty=true returns true", () => {
        expect(exprToBoolean("", true)).toBe(true);
    });
});
