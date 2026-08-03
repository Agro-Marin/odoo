// @ts-check

import { afterEach, describe, expect, test } from "@odoo/hoot";
import { makeActiveElementStack } from "@web/ui/active_element_stack";

describe.current.tags("headless");

/** @type {HTMLElement[]} */
const created = [];

/**
 * @param {HTMLElement} [parent]
 * @returns {HTMLElement}
 */
function el(parent) {
    const node = document.createElement("div");
    (parent ?? document.body).appendChild(node);
    created.push(node);
    return node;
}

afterEach(() => {
    for (const node of created.splice(0)) {
        node.remove();
    }
});

test("starts on document and never pops past it", () => {
    const stack = makeActiveElementStack();
    expect(stack.current).toBe(document);

    expect(stack.deactivate(/** @type {any} */ (document))).toBe(true);
    expect(stack.current).toBe(/** @type {any} */ (undefined));
});

test("activate/deactivate is last-in first-out", () => {
    const stack = makeActiveElementStack();
    const a = el();
    const b = el();

    stack.activate(a);
    expect(stack.current).toBe(a);
    stack.activate(b);
    expect(stack.current).toBe(b);

    stack.deactivate(b);
    expect(stack.current).toBe(a);
    stack.deactivate(a);
    expect(stack.current).toBe(document);
});

test("an element deactivated out of order leaves the rest of the stack intact", () => {
    const stack = makeActiveElementStack();
    const a = el();
    const b = el();

    stack.activate(a);
    stack.activate(b);
    stack.deactivate(a);

    expect(stack.current).toBe(b);
});

test("one deactivation releases one activation, not all of them", () => {
    const stack = makeActiveElementStack();
    const host = el();
    const overlay = el();

    stack.activate(host);
    stack.activate(overlay);
    stack.activate(host);

    stack.deactivate(overlay);
    expect(stack.current).toBe(host);

    stack.deactivate(host);
    expect(stack.current).toBe(host);

    stack.deactivate(host);
    expect(stack.current).toBe(document);
});

test("deactivating something never activated reports it and changes nothing", () => {
    const stack = makeActiveElementStack();
    const a = el();
    stack.activate(a);

    expect(stack.deactivate(el())).toBe(false);
    expect(stack.current).toBe(a);
});

test("activeElementOf returns the innermost claimant", () => {
    const stack = makeActiveElementStack();
    const outer = el();
    const inner = el(outer);
    const leaf = el(inner);

    expect(stack.activeElementOf(leaf)).toBe(document);

    stack.activate(outer);
    expect(stack.activeElementOf(leaf)).toBe(outer);

    stack.activate(inner);
    expect(stack.activeElementOf(leaf)).toBe(inner);

    // Innermost by stack position, not by DOM depth: the last claim wins.
    stack.deactivate(inner);
    expect(stack.activeElementOf(leaf)).toBe(outer);
});

test("activeElementOf ignores active elements that do not contain the node", () => {
    const stack = makeActiveElementStack();
    const sibling = el();
    const other = el();

    stack.activate(sibling);
    expect(stack.activeElementOf(other)).toBe(document);
});

test("reset drops every claim", () => {
    const stack = makeActiveElementStack();
    stack.activate(el());
    stack.activate(el());

    stack.reset();

    expect(stack.current).toBe(document);
});
