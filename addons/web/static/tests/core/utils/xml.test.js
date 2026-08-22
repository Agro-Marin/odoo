// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { createElement, formatXML, parseXML } from "@web/core/utils/dom/xml";

describe.current.tags("headless");

test("parse error throws an exception", () => {
    expect(() => parseXML("<invalid'>")).toThrow("error occured while parsing");
    expect(() => parseXML("<div><div>Valid</div><div><Invalid</div></div>")).toThrow(
        "error occured while parsing",
    );
});

describe("createElement argument shapes", () => {
    test("a string argument becomes a text child", () => {
        expect(createElement("div", "hello").textContent).toBe("hello");
        expect(createElement("div", "a", "b").textContent).toBe("ab");
        const withAttr = createElement("div", { class: "x" }, "t");
        expect(withAttr.getAttribute("class")).toBe("x");
        expect(withAttr.textContent).toBe("t");
        expect(withAttr.childNodes.length).toBe(1);
    });

    test("attribute maps and iterable children still work", () => {
        const child = createElement("span");
        const el = createElement("div", { class: "x", id: "y" }, [child]);
        expect(el.getAttribute("class")).toBe("x");
        expect(el.getAttribute("id")).toBe("y");
        expect(el.children.length).toBe(1);
        const empty = createElement("div", null, undefined, false, "");
        expect(empty.childNodes.length).toBe(0);
        expect(empty.attributes.length).toBe(0);
        expect(createElement("t", []).childNodes.length).toBe(0);
    });

    test("an argument of an unusable type throws instead of being dropped", () => {
        expect(() => createElement("div", 42)).toThrow(/cannot use a number/);
        expect(() => createElement("div", true)).toThrow(/cannot use a boolean/);
        expect(() => createElement("div", () => {})).toThrow(/cannot use a function/);
    });
});

test("formatXML does not crash on unbalanced XML", () => {
    expect(() => formatXML("<div></div></div>")).not.toThrow();
    expect(() => formatXML("</div>")).not.toThrow();
    const out = formatXML("<a><b>x</b></a>");
    expect(out).toInclude("<a>");
    expect(out).toInclude("<b>x</b>");
});
