// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getClassNameFromDecoration, getDecoration } from "@web/core/utils/decorations";

describe.current.tags("headless");

/**
 * @param {Record<string, string>} attrs
 * @returns {Element}
 */
function nodeWith(attrs) {
    const el = document.createElement("field");
    for (const [name, value] of Object.entries(attrs)) {
        el.setAttribute(name, value);
    }
    return el;
}

test("getClassNameFromDecoration: bf and it are the two non-text specials", () => {
    expect(getClassNameFromDecoration("bf")).toBe("fw-bold");
    expect(getClassNameFromDecoration("it")).toBe("fst-italic");
});

test("getClassNameFromDecoration: every other name maps to text-<name>", () => {
    for (const name of [
        "danger",
        "warning",
        "success",
        "info",
        "muted",
        "primary",
        "secondary",
    ]) {
        expect(getClassNameFromDecoration(name)).toBe(`text-${name}`);
    }
    expect(getClassNameFromDecoration("unknown")).toBe("text-unknown");
    expect(getClassNameFromDecoration("")).toBe("text-");
});

test("getDecoration: only decoration-* attributes are collected", () => {
    const node = nodeWith({
        name: "amount",
        widget: "monetary",
        "decoration-danger": "amount < 0",
        class: "o_my_field",
    });
    expect(getDecoration(node)).toEqual([
        { class: "text-danger", condition: "amount < 0" },
    ]);
});

test("getDecoration: strips the decoration- prefix through the class mapping", () => {
    const node = nodeWith({
        "decoration-bf": "state == 'done'",
        "decoration-it": "state == 'draft'",
        "decoration-success": "state == 'posted'",
    });
    expect(getDecoration(node)).toEqual([
        { class: "fw-bold", condition: "state == 'done'" },
        { class: "fst-italic", condition: "state == 'draft'" },
        { class: "text-success", condition: "state == 'posted'" },
    ]);
});

test("getDecoration: preserves attribute order and the raw condition string", () => {
    const node = nodeWith({
        "decoration-warning": "a > 1",
        "decoration-danger": "b and (c or d)",
    });
    const result = getDecoration(node);
    expect(result.map((d) => d.class)).toEqual(["text-warning", "text-danger"]);
    expect(result[1].condition).toBe("b and (c or d)");
});

test("getDecoration: an empty condition is kept (not dropped)", () => {
    const node = nodeWith({ "decoration-info": "" });
    expect(getDecoration(node)).toEqual([{ class: "text-info", condition: "" }]);
});

test("getDecoration: node without decorations yields an empty list", () => {
    expect(getDecoration(nodeWith({ name: "x", widget: "char" }))).toEqual([]);
});
