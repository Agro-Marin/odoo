/** @odoo-module native */
import { registry } from "@web/core/registry";

import {
    SectionAndNoteFieldOne2Many,
    sectionAndNoteFieldOne2Many,
    SectionAndNoteListRenderer,
} from "../section_and_note_fields_backend/section_and_note_fields_backend.js";

export class AccountMergeWizardLinesRenderer extends SectionAndNoteListRenderer {
    setup() {
        super.setup();
        this.titleField = "info";
    }

    getCellClass(column, record) {
        const classNames = super.getCellClass(column, record);
        if (this.isSectionOrNote(record) && column.name === "is_selected") {
            return classNames.replace(" o_hidden", "");
        }
        return classNames;
    }

    /** @override * */
    getSectionColumns(columns) {
        const sectionCols = columns.filter(
            (col) =>
                col.type === "field" &&
                (col.name === this.titleField || col.name === "is_selected"),
        );
        return sectionCols.map((col) => {
            if (col.name === this.titleField) {
                return { ...col, colspan: columns.length - sectionCols.length + 1 };
            } else {
                return { ...col };
            }
        });
    }

    /** @override */
    isSortable(column) {
        return false;
    }
}

export class AccountMergeWizardLinesOne2Many extends SectionAndNoteFieldOne2Many {
    static components = {
        ...SectionAndNoteFieldOne2Many.components,
        ListRenderer: AccountMergeWizardLinesRenderer,
    };
}

export const accountMergeWizardLinesOne2Many = {
    ...sectionAndNoteFieldOne2Many,
    component: AccountMergeWizardLinesOne2Many,
};

registry
    .category("fields")
    .add("account_merge_wizard_lines_one2many", accountMergeWizardLinesOne2Many);
