// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { ListGridState } from "@web/views/list/list_grid_state";

describe.current.tags("headless");

function mockRecord(id) {
    return { id: String(id), resId: id, selected: false };
}

function mockColumn(name, type = "field", readonly = false) {
    return { id: `col_${name}`, name, type, readonly };
}

function mockGroup(id, records, isFolded = false, subGroups = null) {
    const list = {
        records,
        isGrouped: Boolean(subGroups),
        groups: subGroups || [],
    };
    return {
        id: String(id),
        isFolded,
        displayName: `Group ${id}`,
        list,
    };
}

function mockList(records, groups = null) {
    return {
        records: groups ? [] : records,
        isGrouped: Boolean(groups),
        groups: groups || [],
    };
}

function makeGridState(options = {}) {
    const records = options.records || [1, 2, 3, 4, 5].map(mockRecord);
    const columns = options.columns || [
        mockColumn("name"),
        mockColumn("email"),
        mockColumn("phone"),
    ];
    const list = options.list || mockList(records);
    const gridState = new ListGridState({
        list,
        columns,
        hasSelectors: options.hasSelectors ?? false,
        hasOpenFormViewColumn: options.hasOpenFormViewColumn ?? false,
        hasActionsColumn: options.hasActionsColumn ?? false,
        isRTL: options.isRTL ?? false,
        showGroupAddLine: options.showGroupAddLine ?? false,
    });
    gridState.rebuild();
    return gridState;
}

describe("flat row materialization", () => {
    test("ungrouped: 5 records produce 5 flat rows of type 'record'", () => {
        const gs = makeGridState();
        expect(gs.rowCount).toBe(5);
        expect(gs.flatRows.every((r) => r.type === "record")).toBe(true);
        expect(gs.flatRows.map((r) => r.globalIndex)).toEqual([0, 1, 2, 3, 4]);
        expect(gs.flatRows[0].record.id).toBe("1");
        expect(gs.flatRows[4].record.id).toBe("5");
    });

    test("grouped: 2 open groups with records produce correct interleaving", () => {
        const records1 = [1, 2, 3].map(mockRecord);
        const records2 = [4, 5].map(mockRecord);
        const groups = [mockGroup(10, records1), mockGroup(20, records2)];
        const list = mockList([], groups);
        const gs = makeGridState({ list, showGroupAddLine: true });

        expect(gs.rowCount).toBe(9);
        expect(gs.flatRows[0].type).toBe("group");
        expect(gs.flatRows[0].group.id).toBe("10");
        expect(gs.flatRows[1].type).toBe("record");
        expect(gs.flatRows[1].record.id).toBe("1");
        expect(gs.flatRows[3].type).toBe("record");
        expect(gs.flatRows[3].record.id).toBe("3");
        expect(gs.flatRows[4].type).toBe("add-line");
        expect(gs.flatRows[5].type).toBe("group");
        expect(gs.flatRows[5].group.id).toBe("20");
        expect(gs.flatRows[6].type).toBe("record");
        expect(gs.flatRows[6].record.id).toBe("4");
        expect(gs.flatRows[7].type).toBe("record");
        expect(gs.flatRows[7].record.id).toBe("5");
        expect(gs.flatRows[8].type).toBe("add-line");
    });

    test("folded groups produce only header rows, no children", () => {
        const records = [1, 2].map(mockRecord);
        const groups = [
            mockGroup(10, records, true),
            mockGroup(20, [3].map(mockRecord)),
        ];
        const list = mockList([], groups);
        const gs = makeGridState({ list, showGroupAddLine: true });

        expect(gs.rowCount).toBe(4);
        expect(gs.flatRows[0].type).toBe("group");
        expect(gs.flatRows[0].group.isFolded).toBe(true);
        expect(gs.flatRows[1].type).toBe("group");
        expect(gs.flatRows[1].group.id).toBe("20");
        expect(gs.flatRows[2].type).toBe("record");
        expect(gs.flatRows[3].type).toBe("add-line");
    });

    test("nested groups: 2 levels deep with correct depth tracking", () => {
        const innerRecords = [1, 2].map(mockRecord);
        const innerGroup = mockGroup(100, innerRecords);
        const outerGroup = mockGroup(10, [], false, [innerGroup]);
        const list = mockList([], [outerGroup]);
        const gs = makeGridState({ list, showGroupAddLine: true });

        expect(gs.rowCount).toBe(5);
        expect(gs.flatRows[0].depth).toBe(0);
        expect(gs.flatRows[0].type).toBe("group");
        expect(gs.flatRows[1].depth).toBe(1);
        expect(gs.flatRows[1].type).toBe("group");
        expect(gs.flatRows[2].depth).toBe(2);
        expect(gs.flatRows[2].type).toBe("record");
        expect(gs.flatRows[4].depth).toBe(2);
        expect(gs.flatRows[4].type).toBe("add-line");
    });

    test("empty ungrouped list produces 0 flat rows", () => {
        const gs = makeGridState({ records: [], list: mockList([]) });
        expect(gs.rowCount).toBe(0);
    });
});

describe("moveFocus", () => {
    test("up/down ungrouped: correct index arithmetic", () => {
        const gs = makeGridState();
        const down = gs.moveFocus(0, 1, "down");
        expect(down).toEqual({ rowIndex: 1, colIndex: 1 });

        const up = gs.moveFocus(2, 2, "up");
        expect(up).toEqual({ rowIndex: 1, colIndex: 2 });
    });

    test("up/down: null at boundaries", () => {
        const gs = makeGridState();
        expect(gs.moveFocus(0, 0, "up")).toBe(null);
        expect(gs.moveFocus(4, 0, "down")).toBe(null);
    });

    test("up/down grouped: cross group-to-record boundary preserves lastColIndex", () => {
        const records1 = [1, 2].map(mockRecord);
        const groups = [mockGroup(10, records1)];
        const list = mockList([], groups);
        const gs = makeGridState({ list });

        const up = gs.moveFocus(1, 2, "up");
        expect(up).toEqual({ rowIndex: 0, colIndex: 0 });

        const down = gs.moveFocus(0, 0, "down");
        expect(down).toEqual({ rowIndex: 1, colIndex: 2 });
    });

    test("left/right: correct bounds", () => {
        const gs = makeGridState();
        const right = gs.moveFocus(0, 0, "right");
        expect(right).toEqual({ rowIndex: 0, colIndex: 1 });

        const left = gs.moveFocus(0, 1, "left");
        expect(left).toEqual({ rowIndex: 0, colIndex: 0 });

        expect(gs.moveFocus(0, 0, "left")).toBe(null);
        expect(gs.moveFocus(0, 2, "right")).toBe(null);
    });

    test("left/right RTL: direction is swapped", () => {
        const gs = makeGridState({ isRTL: true });
        const result = gs.moveFocus(0, 1, "right");
        expect(result).toEqual({ rowIndex: 0, colIndex: 0 });

        const result2 = gs.moveFocus(0, 0, "left");
        expect(result2).toEqual({ rowIndex: 0, colIndex: 1 });
    });

    test("colCount includes selector/formView/actions columns", () => {
        const gs = makeGridState({
            hasSelectors: true,
            hasOpenFormViewColumn: true,
            hasActionsColumn: true,
        });
        expect(gs.colCount).toBe(6);
        expect(gs.moveFocus(0, 4, "right")).toEqual({ rowIndex: 0, colIndex: 5 });
        expect(gs.moveFocus(0, 5, "right")).toBe(null);
    });
});

describe("reverse lookup", () => {
    test("findRowByRecordId returns correct flat row", () => {
        const gs = makeGridState();
        const row = gs.findRowByRecordId("3");
        expect(row).not.toBe(undefined);
        expect(row.type).toBe("record");
        expect(row.globalIndex).toBe(2);
        expect(row.record.id).toBe("3");
    });

    test("findRowByRecordId returns undefined for missing ID", () => {
        const gs = makeGridState();
        expect(gs.findRowByRecordId("999")).toBe(undefined);
    });

    test("findRowByGroupId returns correct flat row", () => {
        const groups = [mockGroup(10, [1].map(mockRecord))];
        const list = mockList([], groups);
        const gs = makeGridState({ list });

        const row = gs.findRowByGroupId("10");
        expect(row).not.toBe(undefined);
        expect(row.type).toBe("group");
        expect(row.group.id).toBe("10");
    });
});

describe("rebuild", () => {
    test("rebuild after group toggle changes row count", () => {
        const records = [1, 2].map(mockRecord);
        const group = mockGroup(10, records);
        const list = mockList([], [group]);
        const gs = makeGridState({ list, showGroupAddLine: true });

        expect(gs.rowCount).toBe(4);

        group.isFolded = true;
        gs.rebuild();

        expect(gs.rowCount).toBe(1);
        expect(gs.flatRows[0].type).toBe("group");
    });

    test("update + rebuild refreshes with new columns", () => {
        const gs = makeGridState();
        expect(gs.colCount).toBe(3);

        gs.update({ columns: [mockColumn("name"), mockColumn("email")] });
        gs.rebuild();
        expect(gs.colCount).toBe(2);
    });

    test("rebuild preserves lookup consistency", () => {
        const records = [1, 2, 3].map(mockRecord);
        const group = mockGroup(10, records);
        const list = mockList([], [group]);
        const gs = makeGridState({ list });

        const before = gs.findRowByRecordId("2");
        expect(before.globalIndex).toBe(2);

        records.push(mockRecord(4));
        gs.rebuild();

        const after = gs.findRowByRecordId("2");
        expect(after).not.toBe(undefined);
        expect(after.record.id).toBe("2");
    });
});

describe("origin row index validation", () => {
    // `data-row-index` is read off the DOM, which can be one rebuild behind
    // this state (or malformed). moveFocus must answer "no move" rather than
    // throw out of the list's keydown handler.
    test("a rowIndex one past the end yields no move", () => {
        const gs = makeGridState({ records: [1, 2, 3].map(mockRecord) });
        expect(gs.moveFocus(3, 0, "up")).toBe(null);
        expect(gs.moveFocus(3, 0, "down")).toBe(null);
    });

    test("a negative rowIndex yields no move", () => {
        const gs = makeGridState({ records: [1, 2, 3].map(mockRecord) });
        expect(gs.moveFocus(-1, 0, "down")).toBe(null);
        expect(gs.moveFocus(-1, 0, "up")).toBe(null);
    });

    test("a non-numeric rowIndex yields no move", () => {
        const gs = makeGridState({ records: [1, 2, 3].map(mockRecord) });
        expect(gs.moveFocus(Number.NaN, 0, "down")).toBe(null);
        expect(gs.moveFocus(Number.NaN, 0, "up")).toBe(null);
    });
});

describe("canonical column index", () => {
    // A row may render a per-record SUBSET of the grid's columns: the section
    // renderers (account/sale order lines, resource, survey, website_slides)
    // override `ListRenderer.getColumns(record)` to collapse a section row down
    // to a handle + title pair. The cell's position inside its own row is then
    // NOT its position in the grid, so `data-col-index` has to be resolved
    // through the column's identity for arrow navigation to stay on-column.
    test("resolves a column to its position in the full column set", () => {
        const columns = [
            mockColumn("handle"),
            mockColumn("product"),
            mockColumn("name"),
            mockColumn("qty"),
        ];
        const gs = makeGridState({ columns });
        expect(columns.map((c) => gs.getColIndexOfColumn(c))).toEqual([0, 1, 2, 3]);
    });

    test("a section row's truncated subset keeps each column's grid index", () => {
        const columns = [
            mockColumn("handle"),
            mockColumn("product"),
            mockColumn("name"),
            mockColumn("qty"),
        ];
        const gs = makeGridState({ columns });
        // what getSectionColumns() builds: a filtered subset, title spread into
        // a clone carrying a colspan — same `id`, new object identity.
        const sectionColumns = [columns[0], { ...columns[2], colspan: 2 }];
        expect(sectionColumns.map((c) => gs.getColIndexOfColumn(c))).toEqual([0, 2]);
    });

    test("the selector column shifts every index by one", () => {
        const columns = [mockColumn("a"), mockColumn("b")];
        const gs = makeGridState({ columns, hasSelectors: true });
        expect(columns.map((c) => gs.getColIndexOfColumn(c))).toEqual([1, 2]);
    });

    test("a column outside the grid yields undefined, not a bogus index", () => {
        const gs = makeGridState({ columns: [mockColumn("a")] });
        expect(gs.getColIndexOfColumn(mockColumn("gone"))).toBe(undefined);
        expect(gs.getColIndexOfColumn(undefined)).toBe(undefined);
    });

    test("the lookup follows an update() that swaps the columns", () => {
        const first = [mockColumn("a"), mockColumn("b")];
        const second = [mockColumn("b"), mockColumn("a")];
        const gs = makeGridState({ columns: first });
        expect(gs.getColIndexOfColumn(first[0])).toBe(0);
        gs.update({ columns: second });
        gs.rebuild();
        expect(gs.getColIndexOfColumn(second[0])).toBe(0);
        // same id as second[1] -> resolves to its NEW position
        expect(gs.getColIndexOfColumn(first[0])).toBe(1);
    });
});

describe("generation counter", () => {
    test("holds steady when a rebuild finds the same rows", () => {
        // rebuild() runs on EVERY render of the renderer, over every loaded
        // record. Advancing the generation regardless would invalidate
        // ListRecordRow's memo on every render for no reason.
        const gs = makeGridState();
        const first = gs.generation;
        gs.rebuild();
        gs.rebuild();
        expect(gs.generation).toBe(first);
    });

    test("advances whenever the row set changes", () => {
        const records = [1, 2, 3].map(mockRecord);
        const list = mockList(records);
        const gs = makeGridState({ list });
        const first = gs.generation;

        records.push(mockRecord(4));
        gs.rebuild();
        expect(gs.generation).toBe(first + 1);
        expect(gs.rowCount).toBe(4);

        records.pop();
        records.pop();
        gs.rebuild();
        expect(gs.generation).toBe(first + 2);
        expect(gs.rowCount).toBe(2);
    });

    test("is the only signal — instance and array identity are not", () => {
        // `ListRecordRow`'s record/group memoize a lookup into the flat rows.
        // The renderer holds ONE ListGridState for its whole life and
        // `rebuild()` mutates it in place, so a cache keyed on the instance —
        // or on the array — would never invalidate and rows would resolve to
        // stale flat entries.
        const records = [1, 2, 3].map(mockRecord);
        const gs = makeGridState({ list: mockList(records) });
        const before = {
            self: gs,
            rows: gs.flatRows,
            generation: gs.generation,
            row2: gs.findRowByRecordId("2"),
        };

        records.shift();
        gs.rebuild();

        expect(gs).toBe(before.self); // instance unchanged...
        expect(gs.flatRows).toBe(before.rows); // ...array reused in place...
        expect(gs.generation).not.toBe(before.generation); // ...generation is the signal
        expect(gs.findRowByRecordId("2")).not.toBe(before.row2);
        expect(gs.findRowByRecordId("2").globalIndex).toBe(0);
    });
});

describe("update()", () => {
    test("applies every declared option and ignores undefined ones", () => {
        const gs = makeGridState({ hasSelectors: false });
        expect(gs.colCount).toBe(3);
        gs.update({ hasSelectors: true });
        expect(gs.colCount).toBe(4);
        gs.update({ hasSelectors: undefined });
        expect(gs.colCount).toBe(4);
        gs.update({ hasActionsColumn: true, hasOpenFormViewColumn: true });
        expect(gs.colCount).toBe(6);
        gs.update({ isRTL: true });
        expect(gs.isRTL).toBe(true);
    });

    test("columns still rebuild the id-to-index lookup", () => {
        const gs = makeGridState();
        const columns = [mockColumn("a"), mockColumn("b")];
        gs.update({ columns });
        expect(gs.getColIndexOfColumn(columns[1])).toBe(1);
        expect(gs.colCount).toBe(2);
    });
});

describe("moveFocus clamping", () => {
    test("never yields a negative column index when the grid has no columns", () => {
        const gs = makeGridState({
            columns: [],
            list: mockList([1, 2].map(mockRecord)),
        });
        expect(gs.colCount).toBe(0);
        expect(gs.moveFocus(0, 0, "down")).toEqual({ rowIndex: 1, colIndex: 0 });
    });
});
