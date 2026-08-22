// @ts-check
/** @odoo-module native */

export const listSortingMixin = {
    /**
     * @param {{ name: string }} column
     * @returns {boolean}
     */
    isNumericColumn(column) {
        const { type } = this.fields[column.name];
        return ["float", "integer", "monetary"].includes(type);
    },

    /**
     * @param {{ name: string, hasLabel?: boolean, options?: any }} column
     * @returns {boolean}
     */
    isSortable(column) {
        const { hasLabel, name, options } = column;
        const { sortable } = this.fields[name];
        return (sortable || options.allow_order) && hasLabel;
    },

    /**
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
     * @param {{ name: string }} column
     */
    onClickSortColumn(column) {
        if (this.columnWidths.justResized) {
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
     * @param {{ element: HTMLElement }} params
     */
    sortStart({ element }) {
        const table = this.tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const cells = /** @type {HTMLTableCellElement[]} */ ([
            ...element.querySelectorAll("td"),
        ]);
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
     * @param {{ element: HTMLElement }} params
     */
    sortStop({ element }) {
        for (const cell of element.querySelectorAll("td")) {
            cell.style.width = "";
        }
    },
};
