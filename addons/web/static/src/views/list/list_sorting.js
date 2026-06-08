// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_sorting - Column-sort + drag-and-drop helpers extracted from ListRenderer */

/**
 * Sorting cohort extracted from ``ListRenderer``.
 *
 * Same prototype-mixin pattern as ``list_styling.js`` and
 * ``list_group_rendering.js``: subclasses (~71 known across
 * core/enterprise/agromarin) override ``super.isSortable(...)``,
 * ``super.onClickSortColumn(...)``, etc.  Methods must stay on the
 * prototype, so we ship a mixin object installed via
 * ``installListRendererMixin`` (defined in ``list_renderer.js``).
 *
 * Cohort scope:
 *   - Column sortability + numeric-detection predicates that drive
 *     header rendering (``isSortable``, ``isNumericColumn``).
 *   - The sort-icon class string consumed by the ``<th>`` template
 *     (``getSortableIconClass``).
 *   - The header click handler that mutates ``list.orderBy``
 *     (``onClickSortColumn``).
 *   - The drag-and-drop reorder lifecycle (``sortDrop``,
 *     ``sortStart``, ``sortStop``) — these are wired into OWL's
 *     ``useSortable`` hook from ``setup()``; the hook stays in the
 *     renderer (it has its own lifecycle), only the callback bodies
 *     move here.
 *
 * Renderer state these methods read:
 *   - ``this.fields`` (numeric-column type lookup, sortable flag)
 *   - ``this.props.list`` (orderBy, sortBy, resequence, moveRecord,
 *     leaveEditMode, model.useSampleModel, handleField)
 *   - ``this.tableRef`` (sortStart inspects header widths)
 *   - ``this.editedRecord`` (onClickSortColumn skips while editing)
 *   - ``this.preventReorder`` (column-resize guard set by
 *     ``column_width_hook``)
 *   - ``this.resequencePromise`` (set by sortDrop, awaited by other
 *     consumers)
 *
 * Field initialization (``this.preventReorder = false``,
 * ``this.tableRef``) stays in the renderer; only method bodies move.
 */

/**
 * Mixin applied to ``ListRenderer.prototype`` after class declaration.
 */
export const listSortingMixin = {
    /**
     * Whether the column displays numeric data.  Drives
     * right-alignment via the ``o_list_number_th`` class on the
     * header.
     *
     * @param {{ name: string }} column
     * @returns {boolean}
     */
    isNumericColumn(column) {
        const { type } = this.fields[column.name];
        return ["float", "integer", "monetary"].includes(type);
    },

    /**
     * Whether the column should respond to click-to-sort.  Requires
     * the underlying field to declare ``sortable`` (or the column to
     * declare ``options.allow_order``) AND a label — unlabeled
     * columns (e.g. button groups) never sort.
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
     * FontAwesome class string for the sort icon next to a column
     * label.  Renders an ascending/descending arrow when the column
     * is the active sort key, a hidden-but-on-hover sort handle
     * otherwise (for sortable columns), or ``d-none`` for
     * non-sortable columns.
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
     * Header click handler.  Consumes the one-shot
     * ``preventReorder`` guard (set by the column-resize hook to
     * suppress the click that ends a resize drag), short-circuits
     * mid-edit / sample-data states, and dispatches to
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
     * Drop callback for OWL's ``useSortable`` (the row drag-and-drop
     * hook wired in ``setup()``).  Reorders within the same group
     * (``moveRecord``) or the flat list (``resequence``) depending
     * on whether a ``dataGroupId`` is supplied.  Stores the in-flight
     * promise on ``this.resequencePromise`` so other consumers (e.g.
     * the no-content helper) can await it.
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
                    previous.dataset.groupId,
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
     * Start callback for ``useSortable``.  Freezes per-cell widths to
     * the corresponding header widths for the duration of the drag,
     * so the dragged row doesn't visually reflow while the user is
     * holding it.  Cells with colspan > 1 sum the spanned headers'
     * widths.
     *
     * @param {{ element: HTMLElement }} params
     */
    sortStart({ element }) {
        const table = this.tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const cells = /** @type {HTMLTableCellElement[]} */ ([
            ...element.querySelectorAll("td"),
        ]);
        let headerIndex = 0;
        for (const cell of cells) {
            let width = 0;
            for (let i = 0; i < cell.colSpan; i++) {
                const header = headers[headerIndex + i];
                const style = getComputedStyle(header);
                width += parseFloat(style.width);
            }
            cell.style.width = `${width}px`;
            headerIndex += cell.colSpan;
        }
    },

    /**
     * Stop callback for ``useSortable``.  Releases the per-cell
     * widths frozen by ``sortStart`` so layout normalizes back to
     * the table's auto/computed widths.
     *
     * @param {{ element: HTMLElement }} params
     */
    sortStop({ element }) {
        for (const cell of element.querySelectorAll("td")) {
            cell.style.width = null;
        }
    },
};
