// @ts-check

/**
 * Unit tests for the properties list algorithms. These ran only through a
 * mounted form plus a simulated drag-and-drop before they were extracted, which
 * is why the column-boundary arithmetic below had no direct coverage at all.
 */

import { expect, test } from "@odoo/hoot";
import {
    findEnclosingSeparator,
    groupProperties,
    moveGroupTo,
    movePropertyByOffset,
    movePropertyTo,
} from "@web/fields/specialized/properties/properties_layout";

/** @param {string} name @param {object} [extra] */
const prop = (name, extra = {}) => ({ name, type: "char", string: name, ...extra });
/** @param {string} name @param {object} [extra] */
const sep = (name, extra = {}) => ({
    name,
    type: "separator",
    string: name,
    ...extra,
});
const names = (list) => list.map((p) => p.name);
const layout = (groups) =>
    groups.map((g) => `${g.name ?? "-"}:[${names(g.elements).join(",")}]`).join(" | ");

// ---------------------------------------------------------------- grouping

test.tags("headless");
test("groupProperties: no separator, one column", () => {
    const list = [prop("a"), prop("b"), prop("c")];
    expect(layout(groupProperties(list, 1))).toBe("-:[a,b,c]");
});

test.tags("headless");
test("groupProperties: no separator, two columns splits evenly", () => {
    const list = [prop("a"), prop("b"), prop("c"), prop("d")];
    expect(layout(groupProperties(list, 2))).toBe("-:[a,b] | -:[c,d]");
});

test.tags("headless");
test("groupProperties: odd count puts the extra in the first column", () => {
    const list = [prop("a"), prop("b"), prop("c")];
    expect(layout(groupProperties(list, 2))).toBe("-:[a,b] | -:[c]");
});

test.tags("headless");
test("groupProperties: separators define the groups and defeat the column split", () => {
    const list = [prop("a"), sep("s1"), prop("b"), prop("c")];
    // leading group for the properties before the first separator, then s1
    expect(layout(groupProperties(list, 2))).toBe("-:[a] | s1:[b,c]");
});

test.tags("headless");
test("groupProperties: a list starting with a separator has no leading group", () => {
    const list = [sep("s1"), prop("a")];
    expect(layout(groupProperties(list, 1))).toBe("s1:[a]");
});

test.tags("headless");
test("groupProperties: fold state comes from value, falling back to fold_by_default", () => {
    expect(groupProperties([sep("s", { fold_by_default: true })], 1)[0].isFolded).toBe(
        true,
    );
    // an explicit value wins over the default
    expect(
        groupProperties([sep("s", { value: false, fold_by_default: true })], 1)[0]
            .isFolded,
    ).toBe(false);
});

test.tags("headless");
test("groupProperties: a single FOLDED group is not re-dealt into columns", () => {
    const list = [sep("s", { value: true }), prop("a"), prop("b")];
    expect(layout(groupProperties(list, 2))).toBe("s:[a,b]");
});

test.tags("headless");
test("groupProperties: empty list still yields one empty group per column", () => {
    // The column split runs on an empty list too, so the caller gets as many
    // empty columns as it asked for rather than a single one.
    expect(layout(groupProperties([], 1))).toBe("-:[]");
    expect(layout(groupProperties([], 2))).toBe("-:[] | -:[]");
});

// ---------------------------------------------------------------- offset move

test.tags("headless");
test("movePropertyByOffset: up and down", () => {
    const list = [prop("a"), prop("b"), prop("c")];
    expect(movePropertyByOffset(list, "b", "down")).toEqual({
        status: "moved",
        targetIndex: 2,
    });
    expect(names(list)).toEqual(["a", "c", "b"]);
    expect(movePropertyByOffset(list, "b", "up")).toEqual({
        status: "moved",
        targetIndex: 1,
    });
    expect(names(list)).toEqual(["a", "b", "c"]);
});

test.tags("headless");
test("movePropertyByOffset: reports the edges instead of moving", () => {
    const list = [prop("a"), prop("b")];
    expect(movePropertyByOffset(list, "a", "up").status).toBe("at-edge");
    expect(movePropertyByOffset(list, "b", "down").status).toBe("at-edge");
    expect(names(list)).toEqual(["a", "b"]);
});

test.tags("headless");
test("movePropertyByOffset: unknown name", () => {
    expect(movePropertyByOffset([prop("a")], "zz", "up").status).toBe("not-found");
});

// ---------------------------------------------------------------- move to

const moveOpts = (columnsCount = 1) => ({
    columnsCount,
    generateName: () => "new_sep",
    separatorTitle: (i) => `Group ${i}`,
});

test.tags("headless");
test("movePropertyTo: moves after the target", () => {
    const list = [prop("a"), prop("b"), prop("c")];
    movePropertyTo(list, {
        propertyName: "a",
        toPropertyName: "c",
        ...moveOpts(),
    });
    expect(names(list)).toEqual(["b", "c", "a"]);
});

test.tags("headless");
test("movePropertyTo: moveBefore drops ahead of the target", () => {
    const list = [prop("a"), prop("b"), prop("c")];
    movePropertyTo(list, {
        propertyName: "c",
        toPropertyName: "b",
        moveBefore: true,
        ...moveOpts(),
    });
    expect(names(list)).toEqual(["a", "c", "b"]);
    // and the same drop without moveBefore lands on the other side of b
    const after = [prop("a"), prop("b"), prop("c")];
    movePropertyTo(after, {
        propertyName: "a",
        toPropertyName: "b",
        ...moveOpts(),
    });
    expect(names(after)).toEqual(["b", "a", "c"]);
});

test.tags("headless");
test("movePropertyTo: unknown source is a no-op", () => {
    const list = [prop("a")];
    expect(
        movePropertyTo(list, {
            propertyName: "zz",
            toPropertyName: "a",
            ...moveOpts(),
        }),
    ).toBe(null);
    expect(names(list)).toEqual(["a"]);
});

test.tags("headless");
test("movePropertyTo: crossing a column boundary materialises separators", () => {
    // 4 properties over 2 columns -> columnSize 2, so a and c are in different
    // columns. Without a real separator the next re-deal would undo the drop.
    const list = [prop("a"), prop("b"), prop("c"), prop("d")];
    movePropertyTo(list, {
        propertyName: "a",
        toPropertyName: "c",
        ...moveOpts(2),
    });
    const separators = list.filter((p) => p.type === "separator");
    expect(separators).toHaveLength(2);
    // inserted unfolded, so the drop is visible
    expect(separators.every((s) => s.value === false)).toBe(true);
});

test.tags("headless");
test("movePropertyTo: within one column inserts no separator", () => {
    const list = [prop("a"), prop("b"), prop("c"), prop("d")];
    movePropertyTo(list, {
        propertyName: "a",
        toPropertyName: "b",
        ...moveOpts(2),
    });
    expect(list.filter((p) => p.type === "separator")).toHaveLength(0);
});

// ---------------------------------------------------------------- group move

test.tags("headless");
test("moveGroupTo: moves a separator and everything under it", () => {
    const list = [sep("s1"), prop("a"), sep("s2"), prop("b"), prop("c")];
    moveGroupTo(list, "s1", "s2");
    expect(names(list)).toEqual(["s2", "b", "c", "s1", "a"]);
});

test.tags("headless");
test("moveGroupTo: unknown source is a no-op", () => {
    const list = [sep("s1"), prop("a")];
    expect(moveGroupTo(list, "zz", "s1")).toBe(null);
});

test.tags("headless");
test("moveGroupTo: refuses a non-separator", () => {
    const list = [sep("s1"), prop("a")];
    expect(() => moveGroupTo(list, "a", "s1")).toThrow();
});

// ---------------------------------------------------------------- separator lookup

test.tags("headless");
test("findEnclosingSeparator: nearest separator at or above the index", () => {
    const list = [prop("a"), sep("s1"), prop("b"), sep("s2"), prop("c")];
    expect(findEnclosingSeparator(list, 4).name).toBe("s2");
    expect(findEnclosingSeparator(list, 2).name).toBe("s1");
    expect(findEnclosingSeparator(list, 0)).toBe(undefined);
});
