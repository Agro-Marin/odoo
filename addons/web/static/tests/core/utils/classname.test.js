// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { addClassesToElement, mergeClasses } from "@web/core/utils/dom/classname";

describe.current.tags("headless");

describe("addClassesToElement", () => {
    test("adds string classes", () => {
        const el = document.createElement("div");
        addClassesToElement(el, "foo bar");
        expect(el.classList.contains("foo")).toBe(true);
        expect(el.classList.contains("bar")).toBe(true);
    });

    test("adds object classes (truthy values only)", () => {
        const el = document.createElement("div");
        addClassesToElement(el, { active: true, hidden: false, visible: 1 });
        expect(el.classList.contains("active")).toBe(true);
        expect(el.classList.contains("hidden")).toBe(false);
        expect(el.classList.contains("visible")).toBe(true);
    });

    test("handles mixed string and object classes", () => {
        const el = document.createElement("div");
        addClassesToElement(el, "base", { conditional: true, excluded: false });
        expect(el.classList.contains("base")).toBe(true);
        expect(el.classList.contains("conditional")).toBe(true);
        expect(el.classList.contains("excluded")).toBe(false);
    });

    test("handles undefined gracefully", () => {
        const el = document.createElement("div");
        addClassesToElement(el, undefined, "valid");
        expect(el.classList.contains("valid")).toBe(true);
    });

    test("handles extra whitespace in string classes", () => {
        const el = document.createElement("div");
        addClassesToElement(el, "  foo   bar  ");
        expect(el.classList.contains("foo")).toBe(true);
        expect(el.classList.contains("bar")).toBe(true);
    });
});

describe("mergeClasses", () => {
    test("merges string classes into object", () => {
        const result = mergeClasses("foo bar");
        expect(result).toEqual({ foo: true, bar: true });
    });

    test("merges object classes", () => {
        const result = mergeClasses({ a: true, b: false });
        expect(result).toEqual({ a: true, b: false });
    });

    test("later definitions override earlier ones", () => {
        const result = mergeClasses({ active: true }, { active: false });
        expect(result).toEqual({ active: false });
    });

    test("merges multiple mixed sources", () => {
        const result = mergeClasses("base", { conditional: true }, "extra");
        expect(result).toEqual({ base: true, conditional: true, extra: true });
    });

    test("handles undefined in list", () => {
        const result = mergeClasses(undefined, "valid", undefined);
        expect(result).toEqual({ valid: true });
    });

    test("empty string produces empty object", () => {
        // trim().split(/\s+/) on "" yields [""] — but empty string is falsy, returns {}
        const result = mergeClasses("");
        expect(result).toEqual({});
    });
});
