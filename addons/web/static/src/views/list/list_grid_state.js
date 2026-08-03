// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_grid_state */

/**
 * @typedef {"group" | "record" | "add-line"} FlatRowType
 * @typedef {{
 *   type: FlatRowType,
 *   globalIndex: number,
 *   record?: object,
 *   group?: object,
 *   parentGroup?: object,
 *   depth: number,
 * }} FlatRow
 */

const OPTION_FIELDS = {
    list: "_list",
    hasSelectors: "_hasSelectors",
    hasOpenFormViewColumn: "_hasOpenFormViewColumn",
    hasActionsColumn: "_hasActionsColumn",
    isRTL: "_isRTL",
    showGroupAddLine: "_showGroupAddLine",
};

export class ListGridState {
    /**
     * @param {object} options
     * @param {object} options.list
     * @param {object[]} options.columns
     * @param {boolean} [options.hasSelectors]
     * @param {boolean} [options.hasOpenFormViewColumn]
     * @param {boolean} [options.hasActionsColumn]
     * @param {boolean} [options.isRTL]
     * @param {boolean} [options.showGroupAddLine]
     */
    constructor({
        list,
        columns,
        hasSelectors = false,
        hasOpenFormViewColumn = false,
        hasActionsColumn = false,
        isRTL = false,
        showGroupAddLine = false,
    }) {
        this._list = list;
        this._setColumns(columns);
        this._hasSelectors = hasSelectors;
        this._hasOpenFormViewColumn = hasOpenFormViewColumn;
        this._hasActionsColumn = hasActionsColumn;
        this._isRTL = isRTL;
        this._showGroupAddLine = showGroupAddLine;

        /** @type {FlatRow[]} */
        this._flatRows = [];
        /** @type {Map<string, FlatRow>} */
        this._rowByRecordId = new Map();
        /** @type {Map<string, FlatRow>} */
        this._rowByGroupId = new Map();
        /** @type {Map<string, FlatRow>} */
        this._addLineByGroupId = new Map();

        this._lastColIndex = 0;

        /** write position within `_flatRows` during a rebuild @type {number} */
        this._cursor = 0;
        /** whether the current rebuild changed anything @type {boolean} */
        this._dirty = false;

        /**
         * @type {number}
         */
        this._generation = 0;
    }

    /** @returns {number} */
    get generation() {
        return this._generation;
    }

    /**
     * @param {object} options
     */
    update(options) {
        for (const [name, field] of Object.entries(OPTION_FIELDS)) {
            if (options[name] !== undefined) {
                this[field] = options[name];
            }
        }
        if (options.columns !== undefined) {
            this._setColumns(options.columns);
        }
    }

    /**
     * Re-materializes the flat rows. This runs on every render of the renderer,
     * over every LOADED record — a 400-row page re-materializes 400 rows to put
     * ~27 in the DOM — so rows are updated in place and the maps are cleared
     * rather than reallocated. `_generation` only advances when the structure
     * actually changed, which is what lets row components skip their lookup.
     */
    rebuild() {
        this._rowByRecordId.clear();
        this._rowByGroupId.clear();
        this._addLineByGroupId.clear();
        this._cursor = 0;
        this._dirty = false;
        this._materialize(this._list, 0, null);
        if (this._flatRows.length !== this._cursor) {
            this._flatRows.length = this._cursor;
            this._dirty = true;
        }
        if (this._dirty) {
            this._generation++;
        }
    }

    /**
     * Writes the row for the current cursor position, reusing the object
     * already there when it describes the same thing.
     *
     * @param {FlatRowType} type
     * @param {object} fields
     */
    _emitRow(type, fields) {
        const index = this._cursor++;
        const existing = this._flatRows[index];
        if (
            existing &&
            existing.type === type &&
            existing.record === fields.record &&
            existing.group === fields.group &&
            existing.parentGroup === fields.parentGroup &&
            existing.depth === fields.depth
        ) {
            return existing;
        }
        const row = { type, globalIndex: index, ...fields };
        this._flatRows[index] = row;
        this._dirty = true;
        return row;
    }

    /** @returns {FlatRow[]} */
    get flatRows() {
        return this._flatRows;
    }

    /** @returns {number} */
    get rowCount() {
        return this._flatRows.length;
    }

    /** @returns {boolean} */
    get isRTL() {
        return this._isRTL;
    }

    /**
     * @param {number} rowIndex
     * @returns {FlatRow | undefined}
     */
    rowAt(rowIndex) {
        return this._flatRows[rowIndex];
    }

    /**
     * @param {number} colIndex
     */
    rememberColumn(colIndex) {
        this._lastColIndex = colIndex;
    }

    /**
     * @returns {number}
     */
    get colCount() {
        let count = this._columns.length;
        if (this._hasSelectors) {
            count++;
        }
        if (this._hasOpenFormViewColumn) {
            count++;
        }
        if (this._hasActionsColumn) {
            count++;
        }
        return count;
    }

    /**
     * @param {string} recordId
     * @returns {FlatRow | undefined}
     */
    findRowByRecordId(recordId) {
        return this._rowByRecordId.get(recordId);
    }

    /**
     * @param {string} groupId
     * @returns {FlatRow | undefined}
     */
    findRowByGroupId(groupId) {
        return this._rowByGroupId.get(groupId);
    }

    /**
     * @param {string} groupId
     * @returns {FlatRow | undefined}
     */
    findAddLineByGroupId(groupId) {
        return this._addLineByGroupId.get(groupId);
    }

    /**
     * @param {object} column
     * @returns {number | undefined}
     */
    getColIndexOfColumn(column) {
        const idx = this._colIndexById.get(column?.id);
        if (idx === undefined) {
            return undefined;
        }
        return idx + (this._hasSelectors ? 1 : 0);
    }

    /**
     * @param {object[]} columns
     */
    _setColumns(columns) {
        this._columns = columns;
        this._colIndexById = new Map(columns.map((col, index) => [col.id, index]));
    }

    /**
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {"up" | "down" | "left" | "right"} direction
     * @returns {{ rowIndex: number, colIndex: number } | null}
     */
    moveFocus(rowIndex, colIndex, direction) {
        const effectiveDir = this._effectiveDirection(direction);
        switch (effectiveDir) {
            case "up":
                return this._moveVertical(rowIndex, colIndex, -1);
            case "down":
                return this._moveVertical(rowIndex, colIndex, 1);
            case "left":
                return this._moveHorizontal(rowIndex, colIndex, -1);
            case "right":
                return this._moveHorizontal(rowIndex, colIndex, 1);
        }
        return null;
    }

    /**
     * @param {object} list
     * @param {number} depth
     * @param {object | null} parentGroup
     */
    _materialize(list, depth, parentGroup) {
        if (list.isGrouped) {
            for (const group of list.groups) {
                const groupRow = this._emitRow("group", {
                    group,
                    record: undefined,
                    parentGroup,
                    depth,
                });
                this._rowByGroupId.set(String(group.id), groupRow);

                if (!group.isFolded) {
                    this._materialize(group.list, depth + 1, group);
                }
            }
        } else {
            for (const record of list.records) {
                const recordRow = this._emitRow("record", {
                    record,
                    group: undefined,
                    parentGroup,
                    depth,
                });
                this._rowByRecordId.set(String(record.id), recordRow);
            }
            if (parentGroup && this._showGroupAddLine) {
                const addLineRow = this._emitRow("add-line", {
                    record: undefined,
                    group: undefined,
                    parentGroup,
                    depth,
                });
                this._addLineByGroupId.set(String(parentGroup.id), addLineRow);
            }
        }
    }

    /**
     * @param {"up" | "down" | "left" | "right"} direction
     * @returns {"up" | "down" | "left" | "right"}
     */
    _effectiveDirection(direction) {
        if (!this._isRTL) {
            return direction;
        }
        if (direction === "left") {
            return "right";
        }
        if (direction === "right") {
            return "left";
        }
        return direction;
    }

    /**
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {number} step
     * @returns {{ rowIndex: number, colIndex: number } | null}
     */
    _moveVertical(rowIndex, colIndex, step) {
        const currentRow = this._flatRows[rowIndex];
        if (!currentRow) {
            return null;
        }
        const nextRowIndex = rowIndex + step;
        const nextRow = this._flatRows[nextRowIndex];
        if (!nextRow) {
            return null;
        }

        const currentIsRecord = currentRow.type === "record";
        if (currentIsRecord) {
            this._lastColIndex = colIndex;
        }
        if (nextRow.type === "group") {
            return { rowIndex: nextRowIndex, colIndex: 0 };
        }
        const targetCol = currentIsRecord ? colIndex : this._lastColIndex || 0;
        return {
            rowIndex: nextRowIndex,
            colIndex: Math.max(0, Math.min(targetCol, this.colCount - 1)),
        };
    }

    /**
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {number} step
     * @returns {{ rowIndex: number, colIndex: number } | null}
     */
    _moveHorizontal(rowIndex, colIndex, step) {
        const nextCol = colIndex + step;
        if (nextCol < 0 || nextCol >= this.colCount) {
            return null;
        }
        if (this._flatRows[rowIndex]?.type === "record") {
            this._lastColIndex = nextCol;
        }
        return { rowIndex, colIndex: nextCol };
    }
}
