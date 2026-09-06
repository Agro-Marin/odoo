// @ts-check
/** @odoo-module native */

import { getElementToFocus } from "./list_focus.js";

/**
 * @typedef {Pick<
 * import("./list_renderer").ListGridContext,
 * | "getProps"
 * | "getColumns"
 * | "getEditedRecord"
 * | "getControls"
 * | "getCanCreate"
 * | "getDisplayRowCreates"
 * | "isCellReadonly"
 * | "onAdd"
 * | "onEditNextRecord"
 * >} ListEditContext
 */

const EDIT_HANDLER_NAMES = [
    "focusCell",
    "applyCellKeydownEditModeStayOnRow",
    "applyCellKeydownMultiEditMode",
    "applyCellKeydownEditModeGroup",
    "onCellKeydownEditMode",
];

export class ListEditHandlers {
    /**
     * @param {any} nav the navigation object the handlers are installed on;
     *        cross-calls go through it so an override on it is honoured
     * @param {any} tableRef
     * @param {ListEditContext} ctx
     */
    constructor(nav, tableRef, ctx) {
        this.nav = nav;
        this.tableRef = tableRef;
        this.ctx = ctx;
    }

    /**
     * @param {object} column
     * @param {boolean} [forward=true]
     */
    focusCell(column, forward = true) {
        const columns = this.ctx.getColumns();
        const editedRecord = this.ctx.getEditedRecord();
        const index = column
            ? columns.findIndex(
                  (col) => col.id === column.id && col.name === column.name,
              )
            : -1;
        let orderedColumns;
        if (index === -1 && !forward) {
            orderedColumns = columns.toReversed();
        } else {
            const startIndex = index === -1 ? 0 : index;
            orderedColumns = [
                ...columns.slice(startIndex, columns.length),
                ...columns.slice(0, startIndex),
            ];
        }
        for (const col of orderedColumns) {
            if (col.type !== "field" || this.ctx.isCellReadonly(col, editedRecord)) {
                continue;
            }
            const cell = this.tableRef.el.querySelector(
                `.o_selected_row td[name='${col.name}']`,
            );
            if (!cell) {
                continue;
            }
            const toFocus = getElementToFocus(cell);
            if (cell !== toFocus) {
                this.nav.focus(toFocus);
                this.nav.lastEditedCell = { column: col, record: editedRecord };
                break;
            }
        }
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {object} _group
     * @param {object} _record
     * @returns {boolean}
     */
    applyCellKeydownEditModeStayOnRow(hotkey, cell, _group, _record) {
        let toFocus;
        const row = cell.parentElement;
        switch (hotkey) {
            case "tab":
                toFocus = this.nav.findNextFocusableOnRow(row, cell);
                break;
            case "shift+tab":
                toFocus = this.nav.findPreviousFocusableOnRow(row, cell);
                break;
        }
        if (toFocus) {
            this.nav.focus(toFocus);
            return true;
        }
        return false;
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {object} group
     * @param {object} record
     * @returns {boolean}
     */
    applyCellKeydownMultiEditMode(hotkey, cell, group, record) {
        const nav = this.nav;
        const { list } = this.ctx.getProps();
        const row = cell.parentElement;
        let toFocus, futureRecord;
        const index = list.selection.indexOf(record);
        if (nav.lastIsDirty && ["tab", "shift+tab", "enter"].includes(hotkey)) {
            list.leaveEditMode();
            return true;
        }
        if (nav.applyCellKeydownEditModeStayOnRow(hotkey, cell, group, record)) {
            return true;
        }
        switch (hotkey) {
            case "tab":
                futureRecord = list.selection[index + 1] || list.selection[0];
                if (record === futureRecord) {
                    toFocus = nav.findNextFocusableOnRow(row, cell);
                    nav.focus(toFocus);
                    return true;
                }
                break;
            case "shift+tab":
                futureRecord = list.selection[index - 1] || list.selection.at(-1);
                if (record === futureRecord) {
                    toFocus = nav.findPreviousFocusableOnRow(row, cell);
                    nav.focus(toFocus);
                    return true;
                }
                nav.cellToFocus = { forward: false, record: futureRecord };
                break;
            case "enter":
                if (list.selection.length === 1) {
                    list.leaveEditMode();
                    return true;
                }
                futureRecord = list.selection[index + 1] || list.selection[0];
                break;
        }
        if (futureRecord) {
            list.enterEditMode(futureRecord);
            return true;
        }
        return false;
    }

    /**
     * @param {string} hotkey
     * @param {HTMLElement} _cell
     * @param {object} group
     * @param {object} record
     * @returns {boolean}
     */
    applyCellKeydownEditModeGroup(hotkey, _cell, group, record) {
        const { editable } = this.ctx.getProps();
        const groupIndex = group.list.records.indexOf(record);
        const isLastOfGroup = groupIndex === group.list.records.length - 1;
        const isDirty = record.dirty || this.nav.lastIsDirty;
        const isEnterBehavior =
            hotkey === "enter" && (isDirty || !record.canBeAbandoned);
        const isTabBehavior = hotkey === "tab" && isDirty;
        if (
            isLastOfGroup &&
            this.ctx.getCanCreate() &&
            editable === "bottom" &&
            (isEnterBehavior || isTabBehavior)
        ) {
            this.ctx.onAdd({ group });
            return true;
        }
        return false;
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {object | null} group
     * @param {object | null} record
     * @returns {boolean}
     */
    onCellKeydownEditMode(hotkey, cell, group, record) {
        if (!record) {
            return false;
        }
        const nav = this.nav;
        const { list } = this.ctx.getProps();
        const applyMultiEditBehavior = record?.selected && list.model.multiEdit;
        if (
            applyMultiEditBehavior &&
            nav.applyCellKeydownMultiEditMode(hotkey, cell, group, record)
        ) {
            return true;
        }
        if (nav.applyCellKeydownEditModeStayOnRow(hotkey, cell, group, record)) {
            return true;
        }
        if (group && nav.applyCellKeydownEditModeGroup(hotkey, cell, group, record)) {
            return true;
        }
        switch (hotkey) {
            case "tab":
                return this.onTabEditMode(cell, group, record);
            case "shift+tab":
                return this.onShiftTabEditMode(cell, record);
            case "enter":
                this.ctx.onEditNextRecord(record, group);
                return true;
            case "escape":
                this.onEscapeEditMode(cell, group, record);
                return true;
            default:
                return false;
        }
    }

    /**
     * Tab from the last record: a new line where the list creates inline,
     * else a new record when the row is dirty, else the first record again
     * when the list cycles.
     *
     * @param {HTMLTableCellElement} cell
     * @param {object | null} group
     * @param {object} record
     * @returns {boolean}
     */
    onTabEditMode(cell, group, record) {
        const nav = this.nav;
        const { cycleOnTab, list, editable } = this.ctx.getProps();
        const isDirty = record.dirty || nav.lastIsDirty;
        const topReCreate = editable === "top" && record.isNew;
        const index = list.records.indexOf(record);
        const lastIndex = topReCreate ? 0 : list.records.length - 1;
        if (index !== lastIndex) {
            list.enterEditMode(list.records[index + 1]);
            return true;
        }
        if (this.ctx.getDisplayRowCreates()) {
            if (!isDirty && record.isNew) {
                list.leaveEditMode();
                return false;
            }
            const create = this.ctx
                .getControls()
                .find((control) => control.type === "create");
            this.ctx.onAdd({ context: create?.context });
            return true;
        }
        if (isDirty && this.ctx.getCanCreate()) {
            this.ctx.onAdd({ group });
            return true;
        }
        if (!cycleOnTab) {
            return false;
        }
        if (record.canBeAbandoned) {
            list.leaveEditMode();
        }
        const futureRecord = list.records[0];
        if (record === futureRecord) {
            nav.focus(nav.findNextFocusableOnRow(cell.parentElement));
        } else {
            list.enterEditMode(futureRecord);
        }
        return true;
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {object} record
     * @returns {boolean}
     */
    onShiftTabEditMode(cell, record) {
        const nav = this.nav;
        const { cycleOnTab, list } = this.ctx.getProps();
        const index = list.records.indexOf(record);
        if (index !== 0) {
            const futureRecord = list.records[index - 1];
            nav.cellToFocus = { forward: false, record: futureRecord };
            list.enterEditMode(futureRecord);
            return true;
        }
        if (!cycleOnTab) {
            list.leaveEditMode();
            return false;
        }
        if (record.canBeAbandoned) {
            list.leaveEditMode();
        }
        const futureRecord = list.records.at(-1);
        if (record === futureRecord) {
            nav.focus(nav.findPreviousFocusableOnRow(cell.parentElement));
        } else {
            nav.cellToFocus = { forward: false, record: futureRecord };
            list.enterEditMode(futureRecord);
        }
        return true;
    }

    /**
     * Escape discards the row, then focus goes to the nearest thing that
     * still exists: the x2many "add a line", the group's own add line, the
     * cell itself, or the first surviving row when the record was new.
     *
     * @param {HTMLTableCellElement} cell
     * @param {object | null} group
     * @param {object} record
     */
    onEscapeEditMode(cell, group, record) {
        const nav = this.nav;
        const { list } = this.ctx.getProps();
        const row = cell.parentElement;
        list.leaveEditMode({ discard: true });
        const firstAddButton = this.tableRef.el.querySelector(
            ".o_field_x2many_list_row_add a",
        );
        if (firstAddButton) {
            nav.focus(firstAddButton);
            return;
        }
        if (group && record.isNew) {
            const children = [...(row?.parentElement?.children ?? [])];
            const idx = row ? children.indexOf(row) : -1;
            for (let i = idx + 1; i < children.length; i++) {
                const r = children[i];
                if (r.classList.contains("o_group_header")) {
                    break;
                }
                const addCell = [...r.children].find((c) =>
                    c.classList.contains("o_group_field_row_add"),
                );
                if (addCell) {
                    nav.focus(addCell.querySelector("a"));
                    return;
                }
            }
        }
        if (!record.isNew) {
            nav.focus(cell);
            return;
        }
        const survivor = [...this.tableRef.el.querySelectorAll(".o_data_row")].find(
            (r) => r !== row,
        );
        nav.focus(survivor?.querySelector(".o_data_cell"));
    }
}

/**
 * The edit-mode handlers as an object to install on `nav`, each bound to a
 * ListEditHandlers over that `nav`.
 *
 * @param {object} nav
 * @param {any} tableRef
 * @param {ListEditContext} ctx
 * @returns {ListEditHandlers}
 */
export function makeEditHandlers(nav, tableRef, ctx) {
    const handlers = new ListEditHandlers(nav, tableRef, ctx);
    return /** @type {any} */ (
        Object.fromEntries(
            EDIT_HANDLER_NAMES.map((name) => [name, handlers[name].bind(handlers)]),
        )
    );
}
