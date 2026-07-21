// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_keyboard_edit - Edit-mode keyboard handlers (enter/escape, tab, multi-edit) for list view inline editing */

/**
 * Edit-mode keyboard handlers for the list view.
 *
 * Extracted from useListKeyboardNavigation to separate the inline-edit concern
 * (enter/escape, tab between records, multi-edit, group-boundary creation) from
 * the navigation concern (arrow keys, focus management, read-only mode).
 *
 * @see list_keyboard_nav.js for the coordinator that composes these handlers
 */

import { getElementToFocus } from "./list_keyboard_nav.js";

/**
 * Create edit-mode keyboard handlers that are merged onto the navigation object.
 *
 * @param {object} nav - the self object from useListKeyboardNavigation
 * @param {any} tableRef - ref to the <table> element
 * @param {object} options - same options passed to the main hook
 */
export function makeEditHandlers(nav, tableRef, options) {
    const {
        getProps,
        getColumns,
        getEditedRecord,
        getControls,
        getCanCreate,
        getDisplayRowCreates,
        isCellReadonly,
        onAdd,
        onEditNextRecord,
    } = options;

    return {
        /**
         * Focus the first editable cell for the given column on the selected row.
         *
         * @param {object} column
         * @param {boolean} [forward=true]
         */
        focusCell(column, forward = true) {
            const columns = getColumns();
            const editedRecord = getEditedRecord();
            const index = column
                ? columns.findIndex(
                      (col) => col.id === column.id && col.name === column.name,
                  )
                : -1;
            let orderedColumns;
            if (index === -1 && !forward) {
                orderedColumns = columns.toReversed();
            } else {
                // No requested column and forward: start the search at the
                // first column (index -1 would otherwise start at the last).
                const startIndex = index === -1 ? 0 : index;
                orderedColumns = [
                    ...columns.slice(startIndex, columns.length),
                    ...columns.slice(0, startIndex),
                ];
            }
            for (const col of orderedColumns) {
                if (col.type !== "field") {
                    continue;
                }
                if (!isCellReadonly(col, editedRecord)) {
                    const cell = tableRef.el.querySelector(
                        `.o_selected_row td[name='${col.name}']`,
                    );
                    if (cell) {
                        const toFocus = getElementToFocus(cell);
                        if (cell !== toFocus) {
                            nav.focus(toFocus);
                            nav.lastEditedCell = {
                                column: col,
                                record: editedRecord,
                            };
                            break;
                        }
                    }
                }
            }
        },

        /**
         * Handle tab/shift+tab staying on the same row (moving between editable cells).
         *
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
                    toFocus = nav.findNextFocusableOnRow(row, cell);
                    break;
                case "shift+tab":
                    toFocus = nav.findPreviousFocusableOnRow(row, cell);
                    break;
            }
            if (toFocus) {
                nav.focus(toFocus);
                return true;
            }
            return false;
        },

        /**
         * Handle keyboard in multi-edit mode (selected records being edited together).
         *
         * @param {string} hotkey
         * @param {HTMLTableCellElement} cell
         * @param {object} group
         * @param {object} record
         * @returns {boolean}
         */
        applyCellKeydownMultiEditMode(hotkey, cell, group, record) {
            const { list } = getProps();
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
        },

        /**
         * Handle keyboard at the end of a group (create new record in group).
         *
         * @param {string} hotkey
         * @param {HTMLElement} _cell
         * @param {object} group
         * @param {object} record
         * @returns {boolean}
         */
        applyCellKeydownEditModeGroup(hotkey, _cell, group, record) {
            const { editable } = getProps();
            const groupIndex = group.list.records.indexOf(record);
            const isLastOfGroup = groupIndex === group.list.records.length - 1;
            const isDirty = record.dirty || nav.lastIsDirty;
            const isEnterBehavior =
                hotkey === "enter" && (isDirty || !record.canBeAbandoned);
            const isTabBehavior = hotkey === "tab" && isDirty;
            if (
                isLastOfGroup &&
                getCanCreate() &&
                editable === "bottom" &&
                (isEnterBehavior || isTabBehavior)
            ) {
                onAdd({ group });
                return true;
            }
            return false;
        },

        /**
         * Handle keyboard in edit mode (inline editing a single record).
         *
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
            const { cycleOnTab, list } = getProps();
            const row = cell.parentElement;
            const applyMultiEditBehavior = record?.selected && list.model.multiEdit;
            const isDirty = record.dirty || nav.lastIsDirty;
            const topReCreate = getProps().editable === "top" && record.isNew;

            if (
                applyMultiEditBehavior &&
                nav.applyCellKeydownMultiEditMode(hotkey, cell, group, record)
            ) {
                return true;
            }

            if (nav.applyCellKeydownEditModeStayOnRow(hotkey, cell, group, record)) {
                return true;
            }

            if (
                group &&
                nav.applyCellKeydownEditModeGroup(hotkey, cell, group, record)
            ) {
                return true;
            }

            switch (hotkey) {
                case "tab": {
                    const index = list.records.indexOf(record);
                    const lastIndex = topReCreate ? 0 : list.records.length - 1;
                    if (index === lastIndex) {
                        if (getDisplayRowCreates()) {
                            if (!isDirty && record.isNew) {
                                list.leaveEditMode();
                                return false;
                            }
                            // `controls` merges create, delete and button
                            // controls in arch order: resolve the create
                            // control explicitly instead of assuming index 0.
                            const create = getControls().find(
                                (control) => control.type === "create",
                            );
                            onAdd({ context: create?.context });
                        } else if (isDirty && getCanCreate()) {
                            onAdd({ group });
                        } else if (cycleOnTab) {
                            if (record.canBeAbandoned) {
                                list.leaveEditMode();
                            }
                            const futureRecord = list.records[0];
                            if (record === futureRecord) {
                                const toFocus = nav.findNextFocusableOnRow(row);
                                nav.focus(toFocus);
                            } else {
                                list.enterEditMode(futureRecord);
                            }
                        } else {
                            return false;
                        }
                    } else {
                        const futureRecord = list.records[index + 1];
                        list.enterEditMode(futureRecord);
                    }
                    break;
                }
                case "shift+tab": {
                    const index = list.records.indexOf(record);
                    if (index === 0) {
                        if (cycleOnTab) {
                            if (record.canBeAbandoned) {
                                list.leaveEditMode();
                            }
                            const futureRecord = list.records.at(-1);
                            if (record === futureRecord) {
                                const toFocus = nav.findPreviousFocusableOnRow(row);
                                nav.focus(toFocus);
                            } else {
                                nav.cellToFocus = {
                                    forward: false,
                                    record: futureRecord,
                                };
                                list.enterEditMode(futureRecord);
                            }
                        } else {
                            list.leaveEditMode();
                            return false;
                        }
                    } else {
                        const futureRecord = list.records[index - 1];
                        nav.cellToFocus = {
                            forward: false,
                            record: futureRecord,
                        };
                        list.enterEditMode(futureRecord);
                    }
                    break;
                }
                case "enter": {
                    onEditNextRecord(record, group);
                    break;
                }
                case "escape": {
                    list.leaveEditMode({ discard: true });
                    // Discarding a NEW row detaches its <tr> (and ``cell``) on the
                    // next render; focus then falls to <body>, breaking keyboard
                    // navigation (nav.focus on the doomed cell is a no-op — the
                    // removal is async, so it is still connected right now). Focus
                    // a SURVIVING data row's cell instead — one that is not the
                    // row being discarded — so focus stays in the grid after the
                    // render. An existing-record discard keeps its row, so ``cell``
                    // survives and is used as-is.
                    const focusCellOrFallback = () => {
                        if (!record.isNew) {
                            nav.focus(cell);
                            return;
                        }
                        const survivor = [
                            ...tableRef.el.querySelectorAll(".o_data_row"),
                        ].find((r) => r !== row);
                        nav.focus(survivor?.querySelector(".o_data_cell"));
                    };
                    const firstAddButton = tableRef.el.querySelector(
                        ".o_field_x2many_list_row_add a",
                    );
                    if (firstAddButton) {
                        nav.focus(firstAddButton);
                    } else if (group && record.isNew) {
                        const children = [...row.parentElement.children];
                        const idx = children.indexOf(row);
                        for (let i = idx + 1; i < children.length; i++) {
                            const r = children[i];
                            if (r.classList.contains("o_group_header")) {
                                break;
                            }
                            const addCell = [...r.children].find((c) =>
                                c.classList.contains("o_group_field_row_add"),
                            );
                            if (addCell) {
                                const toFocus = addCell.querySelector("a");
                                nav.focus(toFocus);
                                return true;
                            }
                        }
                        focusCellOrFallback();
                    } else {
                        focusCellOrFallback();
                    }
                    break;
                }
                default:
                    return false;
            }
            return true;
        },
    };
}
