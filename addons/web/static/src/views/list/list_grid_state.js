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
    isCellReadonly: "_isCellReadonly",
};

export class ListGridState {
    /**
     * @param {object} options
     * @param {object} options.list
     * @param {object[]} options.columns
     * @param {boolean} options.hasSelectors
     * @param {boolean} options.hasOpenFormViewColumn
     * @param {boolean} options.hasActionsColumn
     * @param {boolean} options.isRTL
     * @param {boolean} options.showGroupAddLine
     * @param {(col: object, rec: object) => boolean} options.isCellReadonly
     */
    constructor({
        list,
        columns,
        hasSelectors = false,
        hasOpenFormViewColumn = false,
        hasActionsColumn = false,
        isRTL = false,
        showGroupAddLine = false,
        isCellReadonly = () => false,
    }) {
        this._list = list;
        this._setColumns(columns);
        this._hasSelectors = hasSelectors;
        this._hasOpenFormViewColumn = hasOpenFormViewColumn;
        this._hasActionsColumn = hasActionsColumn;
        this._isRTL = isRTL;
        this._showGroupAddLine = showGroupAddLine;
        this._isCellReadonly = isCellReadonly;

        /** @type {FlatRow[]} */
        this._flatRows = [];
        /** @type {Map<string, FlatRow>} */
        this._rowByRecordId = new Map();
        /** @type {Map<string, FlatRow>} */
        this._rowByGroupId = new Map();
        /** @type {Map<string, FlatRow>} */
        this._addLineByGroupId = new Map();

        this._lastColIndex = 0;

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

    rebuild() {
        this._generation++;
        this._flatRows = [];
        this._rowByRecordId = new Map();
        this._rowByGroupId = new Map();
        this._addLineByGroupId = new Map();
        this._materialize(this._list, 0, null);
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
     * @param {string} name
     * @returns {number}
     */
    getColIndexByName(name) {
        const offset = this._hasSelectors ? 1 : 0;
        const idx = this._columns.findIndex((col) => col.name === name);
        return idx === -1 ? -1 : idx + offset;
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
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {boolean} forward
     * @returns {{ rowIndex: number, colIndex: number } | null}
     */
    findNextEditableCell(rowIndex, colIndex, forward = true) {
        const row = this._flatRows[rowIndex];
        if (!row || row.type !== "record") {
            return null;
        }
        const step = forward ? 1 : -1;
        const offset = this._hasSelectors ? 1 : 0;
        let ci = colIndex + step;
        while (ci >= offset && ci < offset + this._columns.length) {
            const col = this._columns[ci - offset];
            if (
                col.type === "field" &&
                row.record &&
                !this._isCellReadonly(col, row.record)
            ) {
                return { rowIndex, colIndex: ci };
            }
            ci += step;
        }
        return null;
    }

    /**
     * @param {number} rowIndex
     * @param {number} startColIndex
     * @param {boolean} forward
     * @returns {{ rowIndex: number, colIndex: number, column: object } | null}
     */
    findEditableCellWrapping(rowIndex, startColIndex, forward = true) {
        const row = this._flatRows[rowIndex];
        if (!row || row.type !== "record" || !row.record) {
            return null;
        }
        const offset = this._hasSelectors ? 1 : 0;
        const fieldCount = this._columns.length;
        if (fieldCount === 0) {
            return null;
        }
        const startFieldIdx = Math.max(
            0,
            Math.min(startColIndex - offset, fieldCount - 1),
        );

        for (let i = 0; i < fieldCount; i++) {
            let fieldIdx;
            if (forward) {
                fieldIdx = (startFieldIdx + i) % fieldCount;
            } else {
                fieldIdx = (startFieldIdx - i + fieldCount) % fieldCount;
            }
            const col = this._columns[fieldIdx];
            if (col.type === "field" && !this._isCellReadonly(col, row.record)) {
                return { rowIndex, colIndex: fieldIdx + offset, column: col };
            }
        }
        return null;
    }

    /**
     * @param {number} colIndex
     * @returns {object | null}
     */
    getColumnAt(colIndex) {
        const offset = this._hasSelectors ? 1 : 0;
        const fieldIdx = colIndex - offset;
        if (fieldIdx < 0 || fieldIdx >= this._columns.length) {
            return null;
        }
        return this._columns[fieldIdx];
    }

    /**
     * @param {number} rowIndex
     * @param {number} colIndex
     * @returns {boolean}
     */
    isCellEditable(rowIndex, colIndex) {
        const row = this._flatRows[rowIndex];
        if (!row || row.type !== "record" || !row.record) {
            return false;
        }
        const offset = this._hasSelectors ? 1 : 0;
        const colArrayIdx = colIndex - offset;
        if (colArrayIdx < 0 || colArrayIdx >= this._columns.length) {
            return false;
        }
        const col = this._columns[colArrayIdx];
        return col.type === "field" && !this._isCellReadonly(col, row.record);
    }

    /**
     * @param {object} list
     * @param {number} depth
     * @param {object | null} parentGroup
     */
    _materialize(list, depth, parentGroup) {
        if (list.isGrouped) {
            for (const group of list.groups) {
                const groupRow = {
                    type: /** @type {const} */ ("group"),
                    globalIndex: this._flatRows.length,
                    group,
                    parentGroup,
                    depth,
                };
                this._flatRows.push(groupRow);
                this._rowByGroupId.set(String(group.id), groupRow);

                if (!group.isFolded) {
                    this._materialize(group.list, depth + 1, group);
                }
            }
        } else {
            for (const record of list.records) {
                const recordRow = {
                    type: /** @type {const} */ ("record"),
                    globalIndex: this._flatRows.length,
                    record,
                    parentGroup,
                    depth,
                };
                this._flatRows.push(recordRow);
                this._rowByRecordId.set(String(record.id), recordRow);
            }
            if (parentGroup && this._showGroupAddLine) {
                const addLineRow = {
                    type: /** @type {const} */ ("add-line"),
                    globalIndex: this._flatRows.length,
                    parentGroup,
                    depth,
                };
                this._flatRows.push(addLineRow);
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
