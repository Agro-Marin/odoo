// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_grid_state - Pure state object materializing flat row arrays for index-based list view grid navigation */

/**
 * Materializes a flat array of rows (groups + records interleaved), replacing
 * DOM-walking for arrow-key navigation. Zero framework dependency; testable
 * without a browser. Inspired by AG Grid's CellCtrl/RowCtrl separation.
 */

/**
 * @typedef {"group" | "record" | "add-line"} FlatRowType
 *
 * @typedef {{
 *   type: FlatRowType,
 *   globalIndex: number,
 *   record?: object,
 *   group?: object,
 *   parentGroup?: object,
 *   depth: number,
 * }} FlatRow
 */

/**
 * Constructor / {@link ListGridState#update} option name → backing field.
 * ``columns`` is deliberately absent: it needs {@link ListGridState#_setColumns}
 * to rebuild the id→index lookup, so it is handled explicitly by both callers.
 * Declaring the mapping once keeps ``update`` from drifting out of sync with
 * the constructor every time an option is added.
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
     * @param {object} options.list - Odoo list model (DynamicList/StaticList)
     * @param {object[]} options.columns - Active column descriptors
     * @param {boolean} options.hasSelectors - Whether checkbox column is present
     * @param {boolean} options.hasOpenFormViewColumn - Whether "open form" column is present
     * @param {boolean} options.hasActionsColumn - Whether actions column is present
     * @param {boolean} options.isRTL - Right-to-left layout
     * @param {boolean} options.showGroupAddLine - Whether each group's trailing
     *  "Add a line" row should be materialized. Scoped to GROUPS on purpose: an
     *  ungrouped list renders its create-controls row outside the virtualized
     *  flow (after the bottom spacer, see ``web.ListRenderer.Rows``), so giving
     *  it a flat row would reserve spacer height for a row that is also
     *  rendered separately and leave the scroll extent one row too tall.
     * @param {(col: object, rec: object) => boolean} options.isCellReadonly - Readonly check callback
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

        /** Index tracking for cross-row navigation between group and data rows. */
        this._lastColIndex = 0;

        /**
         * Bumped by every {@link rebuild}. Consumers that memoize a lookup into
         * the flat rows (``ListRecordRow``'s ``record`` / ``group``) key on it:
         * the renderer holds ONE instance for its whole life and rebuild
         * mutates it in place, so object identity can never signal
         * invalidation.
         * @type {number}
         */
        this._generation = 0;

        this.rebuild();
    }

    /** @returns {number} counter identifying the current flat-row materialization */
    get generation() {
        return this._generation;
    }

    /**
     * Update constructor options before a rebuild (called each render cycle).
     *
     * @param {object} options - Same shape as constructor options (partial OK)
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
     * Rebuild the flat row array from the current list/group state.
     * Call after any structural change (group toggle, page, sort).
     */
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

    /** @returns {boolean} whether the grid is laid out right-to-left */
    get isRTL() {
        return this._isRTL;
    }

    /**
     * Flat row at a grid index, or ``undefined`` past either end.
     *
     * @param {number} rowIndex
     * @returns {FlatRow | undefined}
     */
    rowAt(rowIndex) {
        return this._flatRows[rowIndex];
    }

    /**
     * Remember the column to return to when focus crosses a row that does not
     * address columns (a group header, or the ``<thead>`` row — which the grid
     * does not model at all, so the keyboard hook reports it from the DOM).
     *
     * @param {number} colIndex
     */
    rememberColumn(colIndex) {
        this._lastColIndex = colIndex;
    }

    /**
     * Number of navigable columns (field columns + selector + form view + actions).
     *
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
     * Find a flat row by record ID.
     *
     * @param {string} recordId
     * @returns {FlatRow | undefined}
     */
    findRowByRecordId(recordId) {
        return this._rowByRecordId.get(recordId);
    }

    /**
     * Find a flat row by group ID.
     *
     * @param {string} groupId
     * @returns {FlatRow | undefined}
     */
    findRowByGroupId(groupId) {
        return this._rowByGroupId.get(groupId);
    }

    /**
     * Find the add-line flat row for a given group ID.
     *
     * @param {string} groupId
     * @returns {FlatRow | undefined}
     */
    findAddLineByGroupId(groupId) {
        return this._addLineByGroupId.get(groupId);
    }

    /**
     * Get the column index for a field name (within the columns array, offset
     * by the selector column if present).
     *
     * @param {string} name
     * @returns {number} -1 if not found
     */
    getColIndexByName(name) {
        const offset = this._hasSelectors ? 1 : 0;
        const idx = this._columns.findIndex((col) => col.name === name);
        return idx === -1 ? -1 : idx + offset;
    }

    /**
     * Canonical grid column index of a column descriptor.
     *
     * A row may render a per-record SUBSET of the grid's columns:
     * ``ListRenderer.getColumns(record)`` is an override seam, and the section
     * renderers (account/sale order lines, resource, survey, website_slides)
     * use it to collapse a section row down to a handle + title pair. The
     * position of a cell inside its own row is therefore NOT its position in
     * the grid, while every index-based consumer here — ``moveFocus``,
     * ``getColumnAt``, ``isCellEditable``, ``findNextEditableCell`` — addresses
     * the grid. Resolving through the column's identity keeps the DOM's
     * ``data-col-index`` in the one index space they all share.
     *
     * @param {object} column
     * @returns {number | undefined} ``undefined`` when the column is not part
     *   of the grid, so the template omits ``data-col-index`` entirely and
     *   ``findFocusMove`` falls back to the cell's DOM position rather than
     *   trusting a bogus index.
     */
    getColIndexOfColumn(column) {
        const idx = this._colIndexById.get(column?.id);
        if (idx === undefined) {
            return undefined;
        }
        return idx + (this._hasSelectors ? 1 : 0);
    }

    /**
     * Store the active columns and (re)build the id → array-index lookup that
     * backs {@link getColIndexOfColumn}. The map holds raw array indexes so it
     * stays independent of the selector offset, which changes on its own.
     *
     * Rebuilt unconditionally rather than memoized on array identity: ``update``
     * runs per render, but a list carries a handful of columns, and a reference
     * check would go stale the moment a sub-renderer mutated its columns array
     * in place — a silent wrong-column bug traded for an unmeasurable saving.
     *
     * @param {object[]} columns
     */
    _setColumns(columns) {
        this._columns = columns;
        this._colIndexById = new Map(columns.map((col, index) => [col.id, index]));
    }

    /**
     * Index-based focus movement for arrow keys.
     *
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
     * Find the next editable cell starting from (rowIndex, colIndex).
     *
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {boolean} forward - Search direction
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
     * Find the first editable cell starting from a column, wrapping around
     * all columns on the same row. Used by focusCell() for edit-mode entry.
     *
     * @param {number} rowIndex
     * @param {number} startColIndex - Column to start searching from (inclusive)
     * @param {boolean} forward - true: search right then wrap; false: search left then wrap
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
     * Get the column descriptor at a given colIndex.
     *
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
     * Check whether a cell is editable.
     *
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
     * Recursively walk the list structure, building the flat row array.
     *
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
     * Swap left/right for RTL layouts.
     *
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
     * Move vertically between rows.
     *
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {number} step - +1 or -1
     * @returns {{ rowIndex: number, colIndex: number } | null}
     */
    _moveVertical(rowIndex, colIndex, step) {
        // The caller's origin comes from the DOM (``data-row-index``), which can
        // be one rebuild behind this state — or absent/malformed. Require it to
        // name a live row, as ``_moveHorizontal`` already does, so a stale index
        // yields "no move" instead of throwing out of a keydown handler.
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
            // Group headers span the grid: only column 0 is addressable.
            return { rowIndex: nextRowIndex, colIndex: 0 };
        }
        const targetCol = currentIsRecord ? colIndex : this._lastColIndex || 0;
        return {
            rowIndex: nextRowIndex,
            // Clamped at BOTH ends: `colCount` is 0 for a list rendered with no
            // columns at all (every column optional-hidden, or a sub-renderer
            // mid-reconfiguration), and `colCount - 1` alone would hand the
            // caller -1 as a column index.
            colIndex: Math.max(0, Math.min(targetCol, this.colCount - 1)),
        };
    }

    /**
     * Move horizontally between columns within the same row.
     *
     * @param {number} rowIndex
     * @param {number} colIndex
     * @param {number} step - +1 or -1
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
