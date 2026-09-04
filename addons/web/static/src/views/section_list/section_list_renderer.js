// @ts-check
/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { ListRenderer } from "@web/views/list";

/**
 * @typedef {import("@web/model/relational_model/record").RelationalRecord} RelationalRecord
 * @typedef {import("@web/views/list/list_column_utils").Column} Column
 */

export class SectionListRenderer extends ListRenderer {
    setup() {
        super.setup();

        this.displayType = "line_section";

        this.titleField = "display_name";

        useEffect(
            (table) => {
                if (table) {
                    table.classList.add("o_section_list_view");
                }
            },
            () => [this.tableRef.el],
        );
    }

    /** @param {RelationalRecord} record */
    getColumns(record) {
        const columns = super.getColumns(record);
        if (this.isSection(record)) {
            return this.getSectionColumns(columns);
        }
        return columns;
    }

    /** @param {RelationalRecord} record */
    getRowClass(record) {
        const classNames = super.getRowClass(record).split(" ");
        if (this.isSection(record)) {
            classNames.push(`o_is_${this.displayType}`, `fw-bold`);
        }
        return classNames.join(" ");
    }

    /** @param {Column[]} columns */
    getSectionColumns(columns) {
        const sectionColumns = columns.filter((col) => col.widget === "handle");
        let colspan = columns.length - sectionColumns.length;
        if (this.activeActions.onDelete) {
            colspan++;
        }
        const titleCol = columns.find(
            (col) => col.type === "field" && col.name === this.titleField,
        );
        if (!titleCol) {
            throw new Error(
                `${this.constructor.name}: no column named "${this.titleField}" in the list; ` +
                    `a section row has no label to render.`,
            );
        }
        sectionColumns.push({ ...titleCol, colspan });
        return sectionColumns;
    }

    /** @param {RelationalRecord} record */
    isSection(record) {
        return record.data.display_type === this.displayType;
    }

    buildRowApi() {
        return {
            ...super.buildRowApi(),
            isSection: (/** @type {RelationalRecord} */ record) =>
                this.isSection(record),
        };
    }
}
SectionListRenderer.recordRowTemplate = "web.SectionListRenderer.RecordRow";
