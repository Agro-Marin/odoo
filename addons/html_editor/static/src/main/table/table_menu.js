/** @odoo-module native */
import { closestElement } from "@html_editor/utils/dom_traversal";
import { getRowIndex, getSelectedCellsMergeInfo } from "@html_editor/utils/table";
import {
    Component,
    onMounted,
    useEffect,
    useExternalListener,
    useRef,
} from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { _t } from "@web/core/translation";

export class TableMenu extends Component {
    static template = "html_editor.TableMenu";
    static props = {
        type: String,
        moveColumn: Function,
        addColumn: Function,
        removeColumn: Function,
        moveRow: Function,
        addRow: Function,
        removeRow: Function,
        turnIntoHeader: Function,
        turnIntoRow: Function,
        resetRowHeight: Function,
        resetColumnWidth: Function,
        resetTableSize: Function,
        clearColumnContent: Function,
        mergeSelectedCells: Function,
        unmergeSelectedCell: Function,
        clearRowContent: Function,
        close: Function,
        buildTableGrid: Function,
        dropdownState: Object,
        target: { validate: (el) => el.nodeType === Node.ELEMENT_NODE },
        document: { validate: (el) => el.nodeType === Node.DOCUMENT_NODE },
        direction: { type: String, optional: true },
    };
    static defaultProps = { direction: "ltr" };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.dropdownRef = useRef("dropdown");
        onMounted(() => {
            this.overlayEl = this.dropdownRef.el;
        });
        useEffect(
            () => {
                if (this.props.type === "column") {
                    this.isFirst = this.props.target.cellIndex === 0;
                    this.isLast = !this.props.target.nextElementSibling;
                } else {
                    const tr = this.props.target.parentElement;
                    this.isFirst = !tr.previousElementSibling;
                    this.isLast = !tr.nextElementSibling;
                    this.isTableHeader = [...tr.children][0].nodeName === "TH";
                }
                this.tableGrid = this.props.buildTableGrid(
                    closestElement(this.props.target, "table"),
                );
                this.items =
                    this.props.type === "column" ? this.colItems() : this.rowItems();
                this.updatePosition();
            },
            () => [this.props.target],
        );
        if (this.props.document.defaultView.frameElement) {
            useExternalListener(this.props.document, "scroll", () => {
                this.updatePosition();
            });
            useExternalListener(this.props.document, "pointerdown", (ev) => {
                if (!this.overlayEl.contains(ev.target)) {
                    this.props.close();
                }
            });
        }
    }

    get hasCustomTableSize() {
        const table = closestElement(this.props.target, "table");
        if (!table) {
            return false;
        }
        const rows = [...table.rows];
        const firstRowCells = [...rows[0].cells];
        const rowHasHeight = rows.some((row) => row.style.height);
        const cellHasWidth = firstRowCells.some((cell) => cell.style.width);
        return rowHasHeight || cellHasWidth;
    }

    get hasCustomRowHeight() {
        return !!this.props.target.closest("tr").style.height;
    }

    get hasCustomColumnWidth() {
        return (
            !!this.props.target.closest("td")?.style?.width ||
            !!this.props.target.closest("th")?.style?.width
        );
    }

    updatePosition() {
        const { target, type, direction } = this.props;
        if (!this.overlayEl || !target) {
            return;
        }
        let frameRect = { top: 0, left: 0 };
        let frameElement;
        try {
            frameElement = this.props.document.defaultView.frameElement;
        } catch {
            // We don't access the frameElement if we don't have access to it.
            // (i.e. iframe origin or sandbox restriction)
        }
        if (frameElement) {
            frameRect = frameElement.getBoundingClientRect();
        }
        const targetRect = target.getBoundingClientRect();
        const container = this.overlayEl.parentElement;
        const containerRect = container.getBoundingClientRect();
        const top = frameRect.top + targetRect.top - containerRect.top;
        const left = frameRect.left + targetRect.left - containerRect.left;
        this.overlayEl.classList.remove("h-100", "w-100");
        if (type === "column") {
            Object.assign(this.overlayEl.style, {
                position: "absolute",
                top: `${top - this.overlayEl.offsetHeight}px`,
                left: `${left}px`,
                width: `${targetRect.width}px`,
            });
        } else {
            const isLTR = direction === "ltr";
            const inlineStartOffset = isLTR
                ? left
                : containerRect.right - (frameRect.left + targetRect.right);
            Object.assign(this.overlayEl.style, {
                position: "absolute",
                top: `${top}px`,
                insetInlineStart: `${inlineStartOffset - this.overlayEl.offsetWidth}px`,
                height: `${targetRect.height}px`,
            });
        }
    }
    onSelected(item) {
        item.action(this.props.target);
        this.props.close();
    }

    /**
     * Whether the row the menu hangs off, or the one it would swap with, holds
     * a cell spanning several rows. Such a swap would tear the span apart.
     *
     * @param {'move_up'|'move_down'} position
     * @returns {boolean}
     */
    isCurrentOrAdjacentCellRowSpanned(position) {
        const rowIndex = getRowIndex(this.props.target);
        const adjacentRowIndex = position === "move_down" ? rowIndex + 1 : rowIndex - 1;
        return (
            this.tableGrid[rowIndex]?.some((cell) => cell?.rowSpan > 1) ||
            this.tableGrid[adjacentRowIndex]?.some((cell) => cell?.rowSpan > 1)
        );
    }

    /**
     * Whether the column the menu hangs off, or the one it would swap with,
     * holds a cell spanning several columns. Such a swap would tear the span
     * apart.
     *
     * @param {'move_left'|'move_right'} position
     * @returns {boolean}
     */
    isCurrentOrAdjacentCellColSpanned(position) {
        const columnIndex = this.tableGrid[0].indexOf(this.props.target);
        const adjacentIndex = position === "move_right" ? columnIndex + 1 : columnIndex - 1;
        return this.tableGrid.some(
            (row) => row[columnIndex]?.colSpan > 1 || row[adjacentIndex]?.colSpan > 1,
        );
    }

    colItems() {
        const ltr = this.props.direction === "ltr";
        const { canMerge, canUnmerge, cells, spanType } = getSelectedCellsMergeInfo(
            this.props.document,
            this.tableGrid,
            this.props.target,
        );
        return [
            !this.isFirst && {
                name: "move_left",
                icon: "fa-chevron-left disabled",
                text: ltr ? _t("Move left") : _t("Move right"),
                action: this.props.moveColumn.bind(this, "left"),
                disable: this.isCurrentOrAdjacentCellColSpanned("move_left"),
                tooltip: _t("Merged columns cannot be moved left or right."),
            },
            !this.isLast && {
                name: "move_right",
                icon: "fa-chevron-right",
                text: ltr ? _t("Move right") : _t("Move left"),
                action: this.props.moveColumn.bind(this, "right"),
                disable: this.isCurrentOrAdjacentCellColSpanned("move_right"),
                tooltip: _t("Merged columns cannot be moved left or right."),
            },
            {
                name: "insert_left",
                icon: "fa-plus",
                text: ltr ? _t("Insert left") : _t("Insert right"),
                action: this.props.addColumn.bind(this, "before"),
            },
            {
                name: "insert_right",
                icon: "fa-plus",
                text: ltr ? _t("Insert right") : _t("Insert left"),
                action: this.props.addColumn.bind(this, "after"),
            },
            {
                name: "delete",
                icon: "fa-trash",
                text: _t("Delete"),
                action: this.props.removeColumn.bind(this),
            },
            this.hasCustomColumnWidth && {
                name: "reset_column_size",
                icon: "fa-table",
                text: _t("Reset column size"),
                action: (target) =>
                    this.props.resetColumnWidth(target.closest("td, th")),
            },
            this.hasCustomTableSize && {
                name: "reset_table_size",
                icon: "fa-table",
                text: _t("Reset table size"),
                action: (target) => this.props.resetTableSize(target.closest("table")),
            },
            {
                name: "clear_content",
                icon: "fa-times-circle",
                text: _t("Clear content"),
                action: this.props.clearColumnContent.bind(this),
            },
            cells.length > 1 && {
                name: "merge_cell",
                icon: "fa-compress",
                text: _t("Merge Cells"),
                disable: !canMerge,
                tooltip: _t("Only rows or cells selection can be merged"),
                action: () => this.props.mergeSelectedCells(cells, spanType),
            },
            canUnmerge && {
                name: "unmerge_cell",
                icon: "fa-compress",
                text: _t("Unmerge Cells"),
                action: this.props.unmergeSelectedCell.bind(this),
            },
        ].filter(Boolean);
    }

    rowItems() {
        const { canMerge, canUnmerge, cells, spanType } = getSelectedCellsMergeInfo(
            this.props.document,
            this.tableGrid,
            this.props.target,
        );
        return [
            this.isFirst &&
                !this.isTableHeader && {
                    name: "make_header",
                    icon: "fa-th-large",
                    text: _t("Turn into header"),
                    action: (target) => this.props.turnIntoHeader(target.parentElement),
                },
            this.isFirst &&
                this.isTableHeader && {
                    name: "remove_header",
                    icon: "fa-table",
                    text: _t("Turn into row"),
                    action: (target) => this.props.turnIntoRow(target.parentElement),
                },
            !this.isFirst && {
                name: "move_up",
                icon: "fa-chevron-up",
                text: _t("Move up"),
                action: (target) => this.props.moveRow("up", target.parentElement),
                disable: this.isCurrentOrAdjacentCellRowSpanned("move_up"),
                tooltip: _t("Merged rows cannot be moved up or down."),
            },
            !this.isLast && {
                name: "move_down",
                icon: "fa-chevron-down",
                text: _t("Move down"),
                action: (target) => this.props.moveRow("down", target.parentElement),
                disable: this.isCurrentOrAdjacentCellRowSpanned("move_down"),
                tooltip: _t("Merged rows cannot be moved up or down."),
            },
            !this.isTableHeader && {
                name: "insert_above",
                icon: "fa-plus",
                text: _t("Insert above"),
                action: (target) => this.props.addRow("before", target.parentElement),
            },
            {
                name: "insert_below",
                icon: "fa-plus",
                text: _t("Insert below"),
                action: (target) => this.props.addRow("after", target.parentElement),
            },
            {
                name: "delete",
                icon: "fa-trash",
                text: _t("Delete"),
                action: (target) => this.props.removeRow(target.parentElement),
            },
            this.hasCustomRowHeight && {
                name: "reset_row_size",
                icon: "fa-table",
                text: _t("Reset row size"),
                action: (target) => this.props.resetRowHeight(target.closest("tr")),
            },
            this.hasCustomTableSize && {
                name: "reset_table_size",
                icon: "fa-table",
                text: _t("Reset table size"),
                action: (target) => this.props.resetTableSize(target.closest("table")),
            },
            {
                name: "clear_content",
                icon: "fa-times-circle",
                text: _t("Clear content"),
                action: (target) => this.props.clearRowContent(target.parentElement),
            },
            cells.length > 1 && {
                name: "merge_cell",
                icon: "fa-compress",
                text: _t("Merge Cells"),
                disable: !canMerge,
                tooltip: _t("Only rows or cells selection can be merged"),
                action: () => this.props.mergeSelectedCells(cells, spanType),
            },
            canUnmerge && {
                name: "unmerge_cell",
                icon: "fa-compress",
                text: _t("Unmerge Cells"),
                action: this.props.unmergeSelectedCell.bind(this),
            },
        ].filter(Boolean);
    }
}
