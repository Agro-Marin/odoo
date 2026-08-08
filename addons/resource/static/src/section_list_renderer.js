/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { ListRenderer } from "@web/views/list";

export class SectionListRenderer extends ListRenderer {
    setup() {
        super.setup();

        this.displayType = "line_section";
        // The column that carries the section's label. `resource.calendar.attendance`
        // has no `title` field -- that name was inherited from survey's renderer,
        // where `survey.question.title` exists. Here the view supplies
        // `display_name` (see resource_calendar_attendance_views.xml), and looking
        // for the wrong name made `getSectionColumns` find nothing, so every
        // section header rendered as an empty band.
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

    getColumns(record) {
        const columns = super.getColumns(record);
        if (this.isSection(record)) {
            return this.getSectionColumns(columns);
        }
        return columns;
    }

    getRowClass(record) {
        const classNames = super.getRowClass(record).split(" ");
        if (this.isSection(record)) {
            classNames.push(`o_is_${this.displayType}`, `fw-bold`);
        }
        return classNames.join(" ");
    }

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
            // Fail loudly rather than pushing `{...undefined, colspan}`, which is a
            // nameless, typeless column descriptor that renders as a blank row and
            // raises nothing -- the exact way the `title` typo above hid for so long.
            throw new Error(
                `${this.constructor.name}: no column named "${this.titleField}" in the list; ` +
                    `a section row has no label to render.`,
            );
        }
        sectionColumns.push({ ...titleCol, colspan });
        return sectionColumns;
    }

    isSection(record) {
        return record.data.display_type === this.displayType;
    }

    /** @override */
    buildRowApi() {
        return {
            ...super.buildRowApi(),
            isSection: (record) => this.isSection(record),
        };
    }
}
SectionListRenderer.recordRowTemplate = "resource.SectionListRenderer.RecordRow";
