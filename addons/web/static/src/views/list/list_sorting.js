// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_sorting - Column-sort + drag-and-drop helpers extracted from ListRenderer */

/**
 * Sorting cohort extracted from ``ListRenderer`` (mixin pattern, like
 * ``list_styling.js`` / ``list_group_rendering.js``): methods must stay on
 * the prototype since ~71 known subclasses across core/enterprise/agromarin
 * override them via ``super.xxx(...)``. Installed via
 * ``installListRendererMixin`` (see ``list_renderer.js``). OWL's
 * ``useSortable`` hook itself stays in the renderer (own lifecycle); only
 * its callback bodies (``sortDrop``/``sortStart``/``sortStop``) move here,
 * as does field init (``preventReorder``, ``tableRef``).
 */

/**
 * Mixin applied to ``ListRenderer.prototype`` after class declaration.
 */
export const listSortingMixin = {
    /**
     * Whether the column displays numeric data; drives right-alignment
     * via the ``o_list_number_th`` header class.
     *
     * @param {{ name: string }} column
     * @returns {boolean}
     */
    isNumericColumn(column) {
        const { type } = this.fields[column.name];
        return ["float", "integer", "monetary"].includes(type);
    },

    /**
     * Whether the column responds to click-to-sort: requires the field to
     * declare ``sortable`` (or the column ``options.allow_order``) AND a
     * label — unlabeled columns (e.g. button groups) never sort.
     *
     * @param {{ name: string, hasLabel?: boolean, options?: any }} column
     * @returns {boolean}
     */
    isSortable(column) {
        const { hasLabel, name, options } = column;
        const { sortable } = this.fields[name];
        return (sortable || options.allow_order) && hasLabel;
    },

    /**
     * FontAwesome class string for a column's sort icon: an
     * ascending/descending arrow when it's the active sort key, a
     * hidden-but-on-hover handle for other sortable columns, or
     * ``d-none`` for non-sortable columns.
     *
     * @param {{ name: string }} column
     * @returns {string}
     */
    getSortableIconClass(column) {
        const { orderBy } = this.props.list;
        const classNames = this.isSortable(column) ? ["fa"] : ["d-none"];
        if (orderBy.length && orderBy[0].name === column.name) {
            classNames.push(orderBy[0].asc ? "fa-sort-asc" : "fa-sort-desc");
        } else {
            classNames.push("fa-sort", "opacity-0", "opacity-100-hover");
        }
        return classNames.join(" ");
    },

    /**
     * Header click handler. Consumes the one-shot ``preventReorder`` guard
     * (set by the column-resize hook to suppress the click ending a resize
     * drag), skips mid-edit/sample-data states, then dispatches to
     * ``list.sortBy`` for sortable columns.
     *
     * @param {{ name: string }} column
     */
    onClickSortColumn(column) {
        if (this.preventReorder) {
            this.preventReorder = false;
            return;
        }
        if (this.editedRecord || this.props.list.model.useSampleModel) {
            return;
        }
        const fieldName = column.name;
        const list = this.props.list;
        if (this.isSortable(column)) {
            list.sortBy(fieldName);
        }
    },

    /**
     * Drop callback for OWL's ``useSortable`` (wired in ``setup()``).
     * Reorders within the same group (``moveRecord``) or the flat list
     * (``resequence``) depending on whether ``dataGroupId`` is supplied.
     * Stores the in-flight promise on ``this.resequencePromise`` so other
     * consumers (e.g. the no-content helper) can await it.
     *
     * @param {string} dataRowId
     * @param {string | null} dataGroupId
     * @param {{ element: HTMLElement, previous: HTMLElement }} params
     */
    async sortDrop(dataRowId, dataGroupId, { element, previous }) {
        element.classList.remove("o_row_draggable");
        const refId = previous ? previous.dataset.id : null;
        try {
            if (dataGroupId) {
                this.resequencePromise = this.props.list.moveRecord(
                    dataRowId,
                    dataGroupId,
                    refId,
                    previous?.dataset.groupId,
                );
            } else {
                this.resequencePromise = this.props.list.resequence(dataRowId, refId, {
                    handleField: this.props.list.handleField,
                });
            }
            await this.resequencePromise;
        } finally {
            element.classList.add("o_row_draggable");
            await this.props.list.leaveEditMode();
        }
    },

    /**
     * Start callback for ``useSortable``. Freezes per-cell widths to the
     * corresponding header widths for the drag's duration, so the dragged
     * row doesn't reflow while held. Colspan > 1 cells sum the spanned
     * headers' widths.
     *
     * @param {{ element: HTMLElement }} params
     */
    sortStart({ element }) {
        const table = this.tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const cells = /** @type {HTMLTableCellElement[]} */ ([
            ...element.querySelectorAll("td"),
        ]);
        // Read all header widths first, then write the cell widths: interleaving
        // the reads (getComputedStyle) with the writes would force one reflow
        // per cell.
        const headerWidths = headers.map((header) =>
            parseFloat(getComputedStyle(header).width),
        );
        let headerIndex = 0;
        for (const cell of cells) {
            let width = 0;
            for (let i = 0; i < cell.colSpan; i++) {
                width += headerWidths[headerIndex + i];
            }
            cell.style.width = `${width}px`;
            headerIndex += cell.colSpan;
        }
    },

    /**
     * Stop callback for ``useSortable``. Releases the per-cell widths
     * frozen by ``sortStart`` so layout normalizes back to the table's
     * auto/computed widths.
     *
     * @param {{ element: HTMLElement }} params
     */
    sortStop({ element }) {
        for (const cell of element.querySelectorAll("td")) {
            cell.style.width = null;
        }
    },
};
