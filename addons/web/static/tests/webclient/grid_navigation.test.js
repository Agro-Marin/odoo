// @ts-check

import { expect, test } from "@odoo/hoot";
import { gridRows, nextFocusedIndex } from "@web/webclient/home_menu/grid_navigation";

test("gridRows wraps each section at the grid's width and keeps one flat index", () => {
    expect(gridRows([5], 6)).toEqual([[0, 1, 2, 3, 4]]);
    expect(gridRows([8], 6)).toEqual([
        [0, 1, 2, 3, 4, 5],
        [6, 7],
    ]);
    expect(gridRows([2, 3], 6)).toEqual([
        [0, 1],
        [2, 3, 4],
    ]);
    expect(gridRows([7, 1], 6)).toEqual([[0, 1, 2, 3, 4, 5], [6], [7]]);
});

test("gridRows gives each item below the grid a row of its own", () => {
    expect(gridRows([2], 6, 3)).toEqual([[0, 1], [2], [3], [4]]);
    expect(gridRows([0, 0], 6, 2)).toEqual([[0], [1]]);
});

test("gridRows on an empty surface is no rows at all", () => {
    expect(gridRows([], 6)).toEqual([]);
    expect(gridRows([0, 0], 6, 0)).toEqual([]);
});

test("the first arrow onto an unfocused grid lands on the first item", () => {
    const rows = gridRows([4], 6);
    for (const move of ["nextLine", "previousLine", "nextColumn", "previousColumn"]) {
        expect(nextFocusedIndex(rows, null, move)).toBe(0);
    }
});

test("both axes wrap", () => {
    const rows = gridRows([6, 6], 6);
    expect(nextFocusedIndex(rows, 5, "nextColumn")).toBe(0, {
        message: "past the end of a row comes back to its start",
    });
    expect(nextFocusedIndex(rows, 0, "previousColumn")).toBe(5);
    expect(nextFocusedIndex(rows, 0, "previousLine")).toBe(6, {
        message: "above the first row is the last",
    });
    expect(nextFocusedIndex(rows, 6, "nextLine")).toBe(0);
});

test("a move onto a shorter row lands on its last item, never past it", () => {
    const rows = gridRows([8], 6);
    expect(nextFocusedIndex(rows, 5, "nextLine")).toBe(7, {
        message: "column 5 has no counterpart on a two-item row",
    });
    expect(nextFocusedIndex(rows, 3, "nextLine")).toBe(7);
    expect(nextFocusedIndex(rows, 1, "nextLine")).toBe(7);
    expect(nextFocusedIndex(rows, 0, "nextLine")).toBe(6);
});

test("a selection the grid no longer holds starts over rather than guessing", () => {
    const rows = gridRows([3], 6);
    expect(nextFocusedIndex(rows, 99, "nextColumn")).toBe(0);
});

test("nothing to focus, or nothing asked, leaves the selection alone", () => {
    expect(nextFocusedIndex([], 0, "nextLine")).toBe(null);
    expect(nextFocusedIndex([], null, "nextLine")).toBe(null);
    expect(nextFocusedIndex(gridRows([3], 6), 1, "Enter")).toBe(null, {
        message: "an unknown move is not a move",
    });
});

test("the tiles and the matching menus are one index space for the arrows", () => {
    const rows = gridRows([2, 3], 6, 2);
    expect(rows).toEqual([[0, 1], [2, 3, 4], [5], [6]]);
    expect(nextFocusedIndex(rows, 2, "nextLine")).toBe(5);
    expect(nextFocusedIndex(rows, 5, "nextLine")).toBe(6);
    expect(nextFocusedIndex(rows, 6, "nextLine")).toBe(0, {
        message: "and past the last menu, back to the top",
    });
});
