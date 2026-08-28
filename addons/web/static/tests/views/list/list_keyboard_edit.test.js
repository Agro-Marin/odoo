// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import { makeEditHandlers } from "@web/views/list/list_keyboard_edit";

describe.current.tags("headless");

function makeTable(/** @type {string} */ rowsHTML) {
    const table = document.createElement("table");
    table.innerHTML = `<tbody>${rowsHTML}</tbody>`;
    document.body.appendChild(table);
    after(() => table.remove());
    return table;
}

const SELECTED_ROW = `
    <tr class="o_selected_row" data-row-index="0">
        <td name="foo" data-col-index="0"><input class="foo"/></td>
        <td name="bar" data-col-index="1"><input class="bar"/></td>
        <td name="baz" data-col-index="2"><span>no input</span></td>
    </tr>`;

/**
 * @param {Record<string, any>} [opts]
 */
function setup({
    columns = [
        { id: 1, name: "foo", type: "field" },
        { id: 2, name: "bar", type: "field" },
    ],
    editedRecord = { id: "r1" },
    props = {},
    isCellReadonly = () => false,
    canCreate = true,
    displayRowCreates = false,
    controls = [],
    rows = SELECTED_ROW,
} = {}) {
    const table = makeTable(rows);
    /** @type {string[]} */
    const steps = [];
    const list = {
        records: [],
        selection: [],
        model: { multiEdit: false },
        enterEditMode: (/** @type {any} */ r) => steps.push(`enterEditMode:${r?.id}`),
        leaveEditMode: () => steps.push("leaveEditMode"),
        ...(props.list || {}),
    };
    const ctx = {
        getProps: () => ({ editable: "bottom", cycleOnTab: true, ...props, list }),
        getColumns: () => columns,
        getEditedRecord: () => editedRecord,
        getControls: () => controls,
        getCanCreate: () => canCreate,
        getDisplayRowCreates: () => displayRowCreates,
        isCellReadonly,
        onAdd: (/** @type {any} */ params) =>
            steps.push(`onAdd:${JSON.stringify(params ?? null)}`),
        onEditNextRecord: () => steps.push("onEditNextRecord"),
    };
    /** @type {any} */
    const nav = {
        lastIsDirty: false,
        lastEditedCell: null,
        cellToFocus: null,
        focus: (/** @type {any} */ el) =>
            steps.push(`focus:${el?.className || el?.tagName}`),
        findNextFocusableOnRow: () => table.querySelector(".bar"),
        findPreviousFocusableOnRow: () => table.querySelector(".foo"),
    };
    Object.assign(nav, makeEditHandlers(nav, { el: table }, ctx));
    return { nav, steps, table, list };
}

describe("focusCell", () => {
    test("starts at the given column and rotates through the rest", () => {
        const { nav, steps } = setup();
        nav.focusCell({ id: 2, name: "bar" });
        expect(steps).toEqual(["focus:bar"]);
    });

    test("with no column it starts at the first", () => {
        const { nav, steps } = setup();
        nav.focusCell(null);
        expect(steps).toEqual(["focus:foo"]);
    });

    test("with no column and forward=false it starts at the last", () => {
        const { nav, steps } = setup();
        nav.focusCell(null, false);
        expect(steps).toEqual(["focus:bar"]);
    });

    test("skips readonly columns", () => {
        const { nav, steps } = setup({
            isCellReadonly: (/** @type {any} */ col) => col.name === "foo",
        });
        nav.focusCell(null);
        expect(steps).toEqual(["focus:bar"]);
    });

    test("skips non-field columns", () => {
        const { nav, steps } = setup({
            columns: [
                { id: 9, name: "handle", type: "widget" },
                { id: 1, name: "foo", type: "field" },
            ],
        });
        nav.focusCell(null);
        expect(steps).toEqual(["focus:foo"]);
    });

    test("skips a cell holding nothing focusable, and records the cell it took", () => {
        const { nav, steps } = setup({
            columns: [
                { id: 3, name: "baz", type: "field" },
                { id: 1, name: "foo", type: "field" },
            ],
        });
        nav.focusCell(null);
        expect(steps).toEqual(["focus:foo"]);
        expect(nav.lastEditedCell.column.name).toBe("foo");
    });

    test("focuses nothing when every column is readonly", () => {
        const { nav, steps } = setup({ isCellReadonly: () => true });
        nav.focusCell(null);
        expect(steps).toEqual([]);
        expect(nav.lastEditedCell).toBe(null);
    });
});

describe("applyCellKeydownEditModeStayOnRow", () => {
    test("tab and shift+tab move within the row and report handled", () => {
        const { nav, steps, table } = setup();
        const cell = table.querySelector("td");

        expect(nav.applyCellKeydownEditModeStayOnRow("tab", cell, null, null)).toBe(
            true,
        );
        expect(
            nav.applyCellKeydownEditModeStayOnRow("shift+tab", cell, null, null),
        ).toBe(true);
        expect(steps).toEqual(["focus:bar", "focus:foo"]);
    });

    test("it declines when the row has nowhere left to go", () => {
        const { nav, steps, table } = setup();
        nav.findNextFocusableOnRow = () => /** @type {any} */ (null);
        const cell = table.querySelector("td");

        expect(nav.applyCellKeydownEditModeStayOnRow("tab", cell, null, null)).toBe(
            false,
        );
        expect(steps).toEqual([]);
    });

    test("it declines any other hotkey outright", () => {
        const { nav, table } = setup();
        const cell = table.querySelector("td");
        expect(nav.applyCellKeydownEditModeStayOnRow("enter", cell, null, null)).toBe(
            false,
        );
        expect(
            nav.applyCellKeydownEditModeStayOnRow("arrowdown", cell, null, null),
        ).toBe(false);
    });
});

describe("applyCellKeydownMultiEditMode", () => {
    /**
     * @param {Record<string, any>} [opts]
     */
    function multi({ selection = [{ id: "a" }, { id: "b" }], dirty = false } = {}) {
        const s = setup({ props: { list: { selection, records: selection } } });
        s.nav.lastIsDirty = dirty;
        return { ...s, selection };
    }

    test("a dirty row leaves edit mode on tab, shift+tab and enter", () => {
        for (const hotkey of ["tab", "shift+tab", "enter"]) {
            const { nav, steps, table, selection } = multi({ dirty: true });
            const cell = table.querySelector("td");
            expect(
                nav.applyCellKeydownMultiEditMode(hotkey, cell, null, selection[0]),
            ).toBe(true);
            expect(steps).toEqual(["leaveEditMode"]);
        }
    });

    test("tab walks to the next selected record", () => {
        const { nav, steps, table, selection } = multi();
        const cell = table.querySelector("td");
        nav.findNextFocusableOnRow = () => /** @type {any} */ (null);

        expect(nav.applyCellKeydownMultiEditMode("tab", cell, null, selection[0])).toBe(
            true,
        );
        expect(steps).toEqual(["enterEditMode:b"]);
    });

    test("tab past the last selected record wraps to the first", () => {
        const { nav, steps, table, selection } = multi();
        nav.findNextFocusableOnRow = () => /** @type {any} */ (null);
        const cell = table.querySelector("td");

        nav.applyCellKeydownMultiEditMode("tab", cell, null, selection[1]);
        expect(steps).toEqual(["enterEditMode:a"]);
    });

    test("a selection of one wraps onto itself and stays in the row", () => {
        const { nav, steps, table, selection } = multi({ selection: [{ id: "only" }] });
        const cell = table.querySelector("td");
        nav.findNextFocusableOnRow = () => /** @type {any} */ (null);

        expect(nav.applyCellKeydownMultiEditMode("tab", cell, null, selection[0])).toBe(
            true,
        );
        expect(steps).toEqual(["focus:undefined"], {
            message: "it focuses within the row rather than re-entering edit mode",
        });
    });

    test("enter with a single selected record leaves edit mode", () => {
        const { nav, steps, table, selection } = multi({ selection: [{ id: "only" }] });
        const cell = table.querySelector("td");

        expect(
            nav.applyCellKeydownMultiEditMode("enter", cell, null, selection[0]),
        ).toBe(true);
        expect(steps).toEqual(["leaveEditMode"]);
    });

    test("shift+tab to a previous record records which way it came", () => {
        const { nav, table, selection } = multi();
        nav.findPreviousFocusableOnRow = () => /** @type {any} */ (null);
        const cell = table.querySelector("td");

        nav.applyCellKeydownMultiEditMode("shift+tab", cell, null, selection[1]);
        expect(nav.cellToFocus).toEqual({ forward: false, record: selection[0] });
    });
});

describe("applyCellKeydownEditModeGroup", () => {
    /**
     * @param {Record<string, any>} [opts]
     */
    function grouped({
        editable = "bottom",
        canCreate = true,
        record,
        index = 1,
    } = {}) {
        const records = [{ id: "x" }, record || { id: "y" }];
        const group = { list: { records } };
        const s = setup({ props: { editable }, canCreate });
        return { ...s, group, record: records[index] };
    }

    test("enter on a dirty last row of the group adds a row to it", () => {
        const { nav, steps, group, record } = grouped({
            record: { id: "y", dirty: true },
        });
        expect(nav.applyCellKeydownEditModeGroup("enter", null, group, record)).toBe(
            true,
        );
        expect(steps).toEqual([`onAdd:${JSON.stringify({ group })}`]);
    });

    test("enter on a clean row that cannot be abandoned also adds", () => {
        const { nav, group, record } = grouped({
            record: { id: "y", canBeAbandoned: false },
        });
        expect(nav.applyCellKeydownEditModeGroup("enter", null, group, record)).toBe(
            true,
        );
    });

    test("tab only adds when the row is dirty", () => {
        const clean = grouped({ record: { id: "y", canBeAbandoned: false } });
        expect(
            clean.nav.applyCellKeydownEditModeGroup(
                "tab",
                null,
                clean.group,
                clean.record,
            ),
        ).toBe(false);

        const dirty = grouped({ record: { id: "y", dirty: true } });
        expect(
            dirty.nav.applyCellKeydownEditModeGroup(
                "tab",
                null,
                dirty.group,
                dirty.record,
            ),
        ).toBe(true);
    });

    test("it declines anywhere but the last row of the group", () => {
        const { nav, group } = grouped({ record: { id: "y", dirty: true } });
        expect(
            nav.applyCellKeydownEditModeGroup(
                "enter",
                null,
                group,
                group.list.records[0],
            ),
        ).toBe(false);
    });

    test("it declines when the list is not bottom-editable, or cannot create", () => {
        const top = grouped({ editable: "top", record: { id: "y", dirty: true } });
        expect(
            top.nav.applyCellKeydownEditModeGroup("enter", null, top.group, top.record),
        ).toBe(false);

        const noCreate = grouped({
            canCreate: false,
            record: { id: "y", dirty: true },
        });
        expect(
            noCreate.nav.applyCellKeydownEditModeGroup(
                "enter",
                null,
                noCreate.group,
                noCreate.record,
            ),
        ).toBe(false);
    });
});

describe("onCellKeydownEditMode dispatch order", () => {
    test("no record at all is not this handler's business", () => {
        const { nav, table } = setup();
        expect(
            nav.onCellKeydownEditMode("tab", table.querySelector("td"), null, null),
        ).toBe(false);
    });

    test("multi-edit is consulted before staying on the row", () => {
        const record = { id: "a", selected: true };
        const { nav, table } = setup({
            props: {
                list: {
                    selection: [record],
                    records: [record],
                    model: { multiEdit: true },
                },
            },
        });
        /** @type {string[]} */
        const order = [];
        nav.applyCellKeydownMultiEditMode = () => (order.push("multi"), true);
        nav.applyCellKeydownEditModeStayOnRow = () => (order.push("row"), true);

        nav.onCellKeydownEditMode("tab", table.querySelector("td"), null, record);
        expect(order).toEqual(["multi"]);
    });

    test("a record that is not selected skips multi-edit even when the list allows it", () => {
        const record = { id: "a", selected: false };
        const { nav, table } = setup({
            props: {
                list: {
                    selection: [record],
                    records: [record],
                    model: { multiEdit: true },
                },
            },
        });
        /** @type {string[]} */
        const order = [];
        nav.applyCellKeydownMultiEditMode = () => (order.push("multi"), true);
        nav.applyCellKeydownEditModeStayOnRow = () => (order.push("row"), true);

        nav.onCellKeydownEditMode("tab", table.querySelector("td"), null, record);
        expect(order).toEqual(["row"]);
    });

    test("the group handler runs only when there is a group, and after the row", () => {
        const record = { id: "a" };
        const { nav, table } = setup({ props: { list: { records: [record] } } });
        /** @type {string[]} */
        const order = [];
        nav.applyCellKeydownEditModeStayOnRow = () => (order.push("row"), false);
        nav.applyCellKeydownEditModeGroup = () => (order.push("group"), true);

        nav.onCellKeydownEditMode("tab", table.querySelector("td"), null, record);
        expect(order).toEqual(["row"], { message: "no group, so no group handler" });

        order.length = 0;
        nav.onCellKeydownEditMode(
            "tab",
            table.querySelector("td"),
            { list: { records: [record] } },
            record,
        );
        expect(order).toEqual(["row", "group"]);
    });
});
