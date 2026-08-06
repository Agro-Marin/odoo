/** @odoo-module native */
import { Component, onWillRender, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { CharField } from "@web/fields/basic/char/char_field";
import { ListTextField, TextField } from "@web/fields/basic/text/text_field";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { x2ManyCommands } from "@web/model/relational_model";
import { ListRenderer } from "@web/views/list";

import {
    DISPLAY_TYPES,
    getPreviousSectionRecords,
    getRecordsUntilSection,
    getSectionRecords,
    hasNextSection,
    hasPreviousSection,
    isSectionOrNoteType,
    isSectionType,
    isSubSectionType,
    isTopSectionType,
} from "./section_and_note_helpers.js";

// Re-exported for external consumers (e.g. sale_management's order line field).
export { getSectionRecords };

const SHOW_ALL_ITEMS_TOOLTIP = _t(
    "Some lines can be on the next page, display them to unlock actions on section.",
);
const DISABLED_MOVE_DOWN_ITEM_TOOLTIP = _t(
    "Some lines of the next section can be on the next page, display them to unlock the action.",
);

export class SectionAndNoteListRenderer extends ListRenderer {
    static template = "account.SectionAndNoteListRenderer";
    static recordRowTemplate = "account.SectionAndNoteListRenderer.RecordRow";
    static props = [
        ...super.props,
        "aggregatedFields",
        "subsections",
        "hidePrices",
        "hideComposition",
    ];

    /** @override */
    setup() {
        super.setup();
        this.titleField = "name";
        this.priceColumns = [...this.props.aggregatedFields, "price_unit"];
        // invisible fields to force copy when duplicating a section
        this.copyFields = ["display_type", "collapse_composition", "collapse_prices"];
        this.parentSectionMap = new Map();
        useEffect(
            (editedRecord) => this.focusToName(editedRecord),
            () => [this.editedRecord],
        );
        onWillRender(() => {
            this.buildParentSectionMap();
        });
    }

    get disabledMoveDownItemTooltip() {
        return DISABLED_MOVE_DOWN_ITEM_TOOLTIP;
    }

    get showAllItemsTooltip() {
        return SHOW_ALL_ITEMS_TOOLTIP;
    }

    /**
     * The section/note members the row template calls (see ListRowApi).
     * Rendering reads keep the row's own record so the reads subscribe the
     * row; the section actions resolve it back to this renderer's context.
     *
     * @override
     */
    buildRowApi() {
        const rec = (record) => this.resolveRowRecord(record);
        return {
            ...super.buildRowApi(),
            isSection: (record) => this.isSection(record),
            isSectionInPage: (record) => this.isSectionInPage(record),
            isTopSection: (record) => this.isTopSection(record),
            isPriceCollapsed: (record) => this.isPriceCollapsed(record),
            isCompositionCollapsed: (record) => this.isCompositionCollapsed(record),
            disablePricesButton: (record) => this.disablePricesButton(record),
            disableCompositionButton: (record) => this.disableCompositionButton(record),
            hasNextSection: (record) => this.hasNextSection(record),
            hasPreviousSection: (record) => this.hasPreviousSection(record),
            isNextSectionInPage: (record) => this.isNextSectionInPage(record),
            getDisabledMoveDownItemTooltip: () => this.disabledMoveDownItemTooltip,
            getShowAllItemsTooltip: () => this.showAllItemsTooltip,
            addRowInSection: (record, addSubSection) =>
                this.addRowInSection(rec(record), addSubSection),
            addNoteInSection: (record) => this.addNoteInSection(rec(record)),
            toggleCollapse: (record, fieldName) =>
                this.toggleCollapse(rec(record), fieldName),
            moveSectionUp: (record) => this.moveSectionUp(rec(record)),
            moveSectionDown: (record) => this.moveSectionDown(rec(record)),
            duplicateSection: (record) => this.duplicateSection(rec(record)),
            deleteSection: (record) => this.deleteSection(rec(record)),
            expandPager: () => this.expandPager(),
        };
    }

    /**
     * The section feature flags the row template reads from `props`, plus the
     * per-row collapse derivations. The derivations depend on the record's
     * PARENT section, which the row itself never reads — computing them here
     * subscribes the renderer to the parent's collapse fields and prop-flips
     * exactly the member rows whose muting changed.
     *
     * @override
     */
    getRowProps(record, group, groupId) {
        return {
            ...super.getRowProps(record, group, groupId),
            readonly: this.props.readonly,
            subsections: this.props.subsections,
            hidePrices: this.props.hidePrices,
            hideComposition: this.props.hideComposition,
            mutedPrices:
                this.props.hidePrices && this.shouldCollapse(record, "collapse_prices"),
            mutedComposition:
                this.props.hideComposition &&
                this.shouldCollapse(record, "collapse_composition"),
        };
    }

    // Current row's collapse state (distinct from the props.hidePrices /
    // props.hideComposition feature flags that gate the toggle buttons).
    isPriceCollapsed(record) {
        return record.data.collapse_prices;
    }

    isCompositionCollapsed(record) {
        return record.data.collapse_composition;
    }

    disablePricesButton(record) {
        return (
            this.shouldCollapse(record, "collapse_prices") ||
            this.disableCompositionButton(record)
        );
    }

    disableCompositionButton(record) {
        return this.shouldCollapse(record, "collapse_composition");
    }

    buildParentSectionMap() {
        this.parentSectionMap.clear();
        let lastSection = null;
        let lastSubSection = null;

        for (const record of this.props.list.records) {
            if (record.data.display_type === DISPLAY_TYPES.SECTION) {
                lastSection = record;
                lastSubSection = null;
                this.parentSectionMap.set(record.id, null);
            } else if (record.data.display_type === DISPLAY_TYPES.SUBSECTION) {
                lastSubSection = record;
                this.parentSectionMap.set(record.id, lastSection);
            } else {
                this.parentSectionMap.set(record.id, lastSubSection ?? lastSection);
            }
        }
    }

    async toggleCollapse(record, fieldName) {
        // We don't want to have 'collapse_prices' & 'collapse_composition' set to True at the same time
        const reverseFieldName =
            fieldName === "collapse_prices"
                ? "collapse_composition"
                : "collapse_prices";
        const changes = {
            [fieldName]: !record.data[fieldName],
            [reverseFieldName]: false,
        };
        await record.update(changes);
    }

    async addNoteInSection(record) {
        const canProceed = await this.props.list.leaveEditMode({ canAbandon: false });
        if (!canProceed) {
            return;
        }

        const records = this.props.list.records;
        const index =
            records.findIndex((r) => r.id === record.id) +
            getSectionRecords(this.props.list, record, true).length -
            1;
        const context = {
            default_display_type: DISPLAY_TYPES.NOTE,
        };
        await this.props.list.addNewRecordAtIndex(index, { context });
    }

    async addRowInSection(record, addSubSection) {
        const canProceed = await this.props.list.leaveEditMode({ canAbandon: false });
        if (!canProceed) {
            return;
        }

        const records = this.props.list.records;
        const index =
            records.findIndex((r) => r.id === record.id) +
            getSectionRecords(this.props.list, record, !addSubSection).length -
            1;
        const context = this.getInsertLineContext(record, addSubSection);
        if (addSubSection) {
            context["default_display_type"] = DISPLAY_TYPES.SUBSECTION;
        }
        await this.props.list.addNewRecordAtIndex(index, { context });
    }

    /**
     * Hook for other modules to conditionally specify defaults for new lines
     */
    getInsertLineContext(_record, _addSubSection) {
        return {};
    }

    canUseFormatter(column, record) {
        if (
            this.isSection(record) &&
            this.props.aggregatedFields.includes(column.name)
        ) {
            return true;
        }
        return super.canUseFormatter(column, record);
    }

    async deleteSection(record) {
        if (this.editedRecord && this.editedRecord !== record) {
            const left = await this.props.list.leaveEditMode({ canAbandon: false });
            if (!left) {
                return;
            }
        }
        if (this.activeActions.onDelete) {
            const method = this.activeActions.unlink ? "unlink" : "delete";
            const commands = [];
            const sectionRecords = getSectionRecords(this.props.list, record);
            for (const sectionRecord of sectionRecords) {
                commands.push(
                    x2ManyCommands[method](
                        sectionRecord.resId || sectionRecord._virtualId,
                    ),
                );
            }
            await this.props.list.applyCommands(commands);
        }
    }

    async duplicateSection(record) {
        const left = await this.props.list.leaveEditMode();
        if (!left) {
            return;
        }

        const { sectionRecords, sectionIndex } = getRecordsUntilSection(
            this.props.list,
            record,
            true,
        );
        const recordsToDuplicate = sectionRecords.filter((record) =>
            this.shouldDuplicateSectionItem(record),
        );
        await this.props.list.duplicateRecords(recordsToDuplicate, {
            targetIndex: sectionIndex,
            copyFields: this.copyFields,
        });
    }

    async editNextRecord(record, group) {
        const canProceed = await this.props.list.leaveEditMode({ validate: true });
        if (!canProceed) {
            return;
        }

        const iter = getRecordsUntilSection(this.props.list, record, true, true);
        if (this.isSection(record) || iter.sectionRecords.length === 1) {
            return this.props.list.addNewRecordAtIndex(iter.sectionIndex - 1);
        } else {
            return super.editNextRecord(record, group);
        }
    }

    expandPager() {
        return this.props.list.load({ limit: this.props.list.count });
    }

    focusToName(editRec) {
        if (editRec && editRec.isNew && this.isSectionOrNote(editRec)) {
            const col = this.columns.find((c) => c.name === this.titleField);
            this.focusCell(col, null);
        }
    }

    hasNextSection(record) {
        return hasNextSection(this.props.list, record);
    }

    hasPreviousSection(record) {
        return hasPreviousSection(this.props.list, record);
    }

    isNextSectionInPage(record) {
        if (this.props.list.count <= this.props.list.offset + this.props.list.limit) {
            // if last page
            return true;
        }
        const sectionRecords = getSectionRecords(this.props.list, record);
        const index =
            this.props.list.records.findIndex((r) => r.id === record.id) +
            sectionRecords.length;
        if (index >= this.props.list.limit) {
            return false;
        }

        const { sectionIndex } = getRecordsUntilSection(
            this.props.list,
            this.props.list.records[index],
            true,
        );
        return sectionIndex < this.props.list.limit;
    }

    isSectionOrNote(record) {
        return isSectionOrNoteType(record);
    }

    isSection(record) {
        return isSectionType(record);
    }

    isSectionInPage(record) {
        if (this.props.list.count <= this.props.list.offset + this.props.list.limit) {
            // if last page
            return true;
        }
        const { sectionIndex } = getRecordsUntilSection(this.props.list, record, true);
        return sectionIndex < this.props.list.limit;
    }

    isSortable() {
        return false;
    }

    isTopSection(record) {
        return isTopSectionType(record);
    }

    isSubSection(record) {
        return isSubSectionType(record);
    }

    /**
     * Determines whether the line should be collapsed.
     * - If the parent is a section: use the parent’s field.
     * - If the parent is a subsection: use parent subsection OR its section.
     * @param {object} record
     * @param {string} fieldName
     * @param {boolean} checkSection - if true, also evaluates the collapse state for section or
     *  subsection records
     * @returns {boolean}
     */
    shouldCollapse(record, fieldName, checkSection = false) {
        const parentSection = this.parentSectionMap.get(record.id);

        if (this.isSection(record) && checkSection) {
            if (this.isTopSection(record)) {
                return record.data[fieldName];
            }
            if (this.isSubSection(record)) {
                return record.data[fieldName] || parentSection?.data[fieldName];
            }
            return false;
        }

        // `line_section` never collapses unless explicitly checked above
        if (this.isTopSection(record)) {
            return false;
        }

        if (!parentSection) {
            return false;
        }

        if (this.isSubSection(parentSection)) {
            const grandParent = this.parentSectionMap.get(parentSection.id);
            return parentSection.data[fieldName] || grandParent?.data[fieldName];
        }

        return !!parentSection.data[fieldName];
    }

    getRowClass(record) {
        const existingClasses = super.getRowClass(record);
        let newClasses = `${existingClasses} o_is_${record.data.display_type}`;
        if (
            this.props.hideComposition &&
            this.shouldCollapse(record, "collapse_composition")
        ) {
            newClasses += " text-muted";
        }
        return newClasses;
    }

    getCellClass(column, record) {
        let classNames = super.getCellClass(column, record);
        // Hide the non-title columns of sections and notes
        if (
            this.isSectionOrNote(record) &&
            column.widget !== "handle" &&
            ![this.titleField, ...this.props.aggregatedFields].includes(column.name)
        ) {
            return `${classNames} o_hidden`;
        }
        // For muting the price columns
        if (
            this.props.hidePrices &&
            this.shouldCollapse(record, "collapse_prices") &&
            this.priceColumns.includes(column.name)
        ) {
            classNames += " text-muted";
        }

        return classNames;
    }

    getColumns(record) {
        const columns = super.getColumns(record);
        if (this.isSectionOrNote(record)) {
            return this.getSectionColumns(columns, record);
        }
        return columns;
    }

    getFormattedValue(column, record) {
        if (
            this.isSection(record) &&
            this.props.aggregatedFields.includes(column.name)
        ) {
            const total = getSectionRecords(this.props.list, record)
                .filter((record) => !this.isSection(record))
                .reduce((total, record) => total + (record.data[column.name] || 0), 0);
            const formatter = registry
                .category("formatters")
                .get(column.fieldType, (val) => val);
            return formatter(total, {
                ...formatter.extractOptions?.(column),
                data: record.data,
                field: record.fields[column.name],
            });
        }
        return super.getFormattedValue(column, record);
    }

    getSectionColumns(columns, record) {
        const sectionCols = columns.filter(
            (col) =>
                col.widget === "handle" ||
                col.name === this.titleField ||
                (this.isSection(record) &&
                    this.props.aggregatedFields.includes(col.name)),
        );
        return sectionCols.map((col) => {
            if (col.name === this.titleField) {
                return { ...col, colspan: columns.length - sectionCols.length + 1 };
            } else {
                return { ...col };
            }
        });
    }

    async moveSectionDown(record) {
        const canProceed = await this.props.list.leaveEditMode({ canAbandon: false });
        if (!canProceed) {
            return;
        }

        const sectionRecords = getSectionRecords(this.props.list, record);
        const index =
            this.props.list.records.findIndex((r) => r.id === record.id) +
            sectionRecords.length;
        const nextSectionRecords = getSectionRecords(
            this.props.list,
            this.props.list.records[index],
        );
        return this.swapSections(sectionRecords, nextSectionRecords);
    }

    async moveSectionUp(record) {
        const canProceed = await this.props.list.leaveEditMode({ canAbandon: false });
        if (!canProceed) {
            return;
        }

        const previousSectionRecords = getPreviousSectionRecords(
            this.props.list,
            record,
        );
        const sectionRecords = getSectionRecords(this.props.list, record);
        return this.swapSections(previousSectionRecords, sectionRecords);
    }

    shouldDuplicateSectionItem(record) {
        return true;
    }

    async swapSections(sectionRecords1, sectionRecords2) {
        const commands = [];
        let sequence = sectionRecords1[0].data[this.props.list.handleField];
        for (const record of sectionRecords2) {
            commands.push(
                x2ManyCommands.update(record.resId || record._virtualId, {
                    [this.props.list.handleField]: sequence++,
                }),
            );
        }
        for (const record of sectionRecords1) {
            commands.push(
                x2ManyCommands.update(record.resId || record._virtualId, {
                    [this.props.list.handleField]: sequence++,
                }),
            );
        }
        await this.props.list.applyCommands(commands, { sort: true });
    }

    /**
     * Reset the `collapse_` fields of a dragged subsection when its parent
     * section is composition-collapsed.
     *
     * @override
     */
    async sortDrop(dataRowId, dataGroupId, options) {
        await super.sortDrop(dataRowId, dataGroupId, options);

        const record = this.props.list.records.find((r) => r.id === dataRowId);
        const parentSection = this.parentSectionMap.get(record.id);
        const commands = [];

        if (this.resetOnResequence(record, parentSection)) {
            commands.push(
                x2ManyCommands.update(record.resId || record._virtualId, {
                    ...this.fieldsToReset(),
                }),
            );
        }

        await this.props.list.applyCommands(commands);
    }

    resetOnResequence(record, parentSection) {
        return (
            this.isSubSection(record) &&
            parentSection?.data.collapse_composition &&
            (record.data.collapse_composition || record.data.collapse_prices)
        );
    }

    fieldsToReset() {
        return {
            ...(this.props.hideComposition && { collapse_composition: false }),
            ...(this.props.hidePrices && { collapse_prices: false }),
        };
    }
}

export class SectionAndNoteFieldOne2Many extends X2ManyField {
    static components = {
        ...super.components,
        ListRenderer: SectionAndNoteListRenderer,
    };
    static props = {
        ...super.props,
        aggregatedFields: Array,
        hideComposition: Boolean,
        hidePrices: Boolean,
        subsections: Boolean,
    };

    get rendererProps() {
        const rp = super.rendererProps;
        if (this.props.viewMode === "list") {
            rp.aggregatedFields = this.props.aggregatedFields;
            rp.hideComposition = this.props.hideComposition;
            rp.hidePrices = this.props.hidePrices;
            rp.subsections = this.props.subsections;
        }
        return rp;
    }
}

export class SectionAndNoteText extends Component {
    static template = "account.SectionAndNoteText";
    static props = { ...standardFieldProps };

    get componentToUse() {
        return this.props.record.data.display_type === "line_section"
            ? CharField
            : TextField;
    }
}

export class ListSectionAndNoteText extends SectionAndNoteText {
    get componentToUse() {
        return this.props.record.data.display_type !== "line_section"
            ? ListTextField
            : super.componentToUse;
    }
}

export const sectionAndNoteFieldOne2Many = {
    ...x2ManyField,
    component: SectionAndNoteFieldOne2Many,
    additionalClasses: [...(x2ManyField.additionalClasses || []), "o_field_one2many"],
    extractProps: (staticInfo, dynamicInfo) => ({
        ...x2ManyField.extractProps(staticInfo, dynamicInfo),
        aggregatedFields: staticInfo.attrs.aggregated_fields
            ? staticInfo.attrs.aggregated_fields.split(/\s*,\s*/)
            : [],
        hideComposition: staticInfo.options?.hide_composition ?? false,
        hidePrices: staticInfo.options?.hide_prices ?? false,
        subsections: staticInfo.options?.subsections ?? false,
    }),
};

export const sectionAndNoteText = {
    component: SectionAndNoteText,
    additionalClasses: ["o_field_text"],
};

export const listSectionAndNoteText = {
    ...sectionAndNoteText,
    component: ListSectionAndNoteText,
};

registry
    .category("fields")
    .add("section_and_note_one2many", sectionAndNoteFieldOne2Many);
registry.category("fields").add("section_and_note_text", sectionAndNoteText);
registry.category("fields").add("list.section_and_note_text", listSectionAndNoteText);
