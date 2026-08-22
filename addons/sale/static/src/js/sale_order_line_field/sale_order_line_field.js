/** @odoo-module native */
import {
    ProductLabelSectionAndNoteListRender,
    ProductLabelSectionAndNoteOne2Many,
    productLabelSectionAndNoteOne2Many,
} from "@account/components/product_label_section_and_note_field/product_label_section_and_note_field_o2m";
import {
    ListSectionAndNoteText,
    listSectionAndNoteText,
    sectionAndNoteFieldOne2Many,
    SectionAndNoteText,
    sectionAndNoteText,
} from "@account/components/section_and_note_fields_backend/section_and_note_fields_backend";
import { useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { CharField } from "@web/fields/basic/char/char_field";

const indexOfRecord = (records, record) => records.findIndex((r) => r.id === record.id);

export function getComboRecords(listRecords, record) {
    const comboRecords = [];

    if (record.data.product_type === "combo") {
        comboRecords.push(record);
        let index = indexOfRecord(listRecords, record) + 1;

        while (index < listRecords.length) {
            const r = listRecords[index];
            if (
                !r.data.combo_item_id?.id ||
                (r.data.linked_line_id?.id !== record.resId &&
                    r.data.linked_virtual_id !== record.data.virtual_id)
            ) {
                break;
            }
            comboRecords.push(r);
            index++;
        }
    } else if (record.data.combo_item_id?.id) {
        let index = indexOfRecord(listRecords, record);
        while (index >= 0) {
            const r = listRecords[index];
            comboRecords.unshift(r);

            if (
                r.data.product_type === "combo" &&
                (r.resId === record.data.linked_line_id?.id ||
                    r.data.virtual_id === record.data.linked_virtual_id)
            ) {
                break;
            }
            index--;
        }
    }

    return comboRecords;
}

export class SaleOrderLineListRenderer extends ProductLabelSectionAndNoteListRender {
    static recordRowTemplate = "sale.ListRenderer.RecordRow";

    setup() {
        super.setup();
        this.priceColumns.push("discount");

        useSubEnv({
            shouldCollapse: this.shouldCollapse.bind(this),
        });
    }

    /**
     * @override
     */
    buildRowApi() {
        const rec = (record) => this.resolveRowRecord(record);
        return {
            ...super.buildRowApi(),
            isCombo: (record) => this.isCombo(rec(record)),
            getComboColumns: () => this.comboColumns,
            getPreviousRecords: (record) => this.getPreviousRecords(rec(record)),
            getNextRecords: (record) => this.getNextRecords(rec(record)),
            moveCombo: (record, direction) => this.moveCombo(rec(record), direction),
            onDeleteRecord: (record) => this.onDeleteRecord(rec(record)),
        };
    }

    get comboColumns() {
        return [
            this.titleField,
            ...this.props.aggregatedFields,
            "product_qty",
            "discount",
        ];
    }

    getCellTitle(column, record) {
        if (column.name === "product_id" || column.name === "product_template_id") {
            return;
        }
        return super.getCellTitle(column, record);
    }

    getActiveColumns() {
        let activeColumns = super.getActiveColumns();
        const productTmplCol = activeColumns.find(
            (col) => col.name === "product_template_id",
        );
        const productCol = activeColumns.find((col) => col.name === "product_id");

        if (productCol && productTmplCol) {
            activeColumns = activeColumns.filter(
                (col) => col.name !== "product_template_id",
            );
        }

        return activeColumns;
    }

    getRowClass(record) {
        let classNames = super.getRowClass(record);
        if (this.isCombo(record) || this.isComboItem(record)) {
            classNames = classNames.replace("o_row_draggable", "");
        }
        return `${classNames} ${this.isCombo(record) ? "o_is_line_section o_is_line_section_no_indent" : ""}`;
    }

    isCellReadonly(column, record) {
        return (
            super.isCellReadonly(column, record) ||
            (this.isComboItem(record) &&
                !["name", "tax_ids", "qty_transferred"].includes(column.name))
        );
    }

    async onDeleteRecord(record) {
        if (this.isCombo(record)) {
            await record.update({ selected_combo_items: JSON.stringify([]) });
        }
        await super.onDeleteRecord(record);
    }

    async moveCombo(record, direction) {
        const canProceed = await this.props.list.leaveEditMode({ canAbandon: false });
        if (!canProceed) {
            return;
        }

        const { movingRecords, targetRecords } = this.getComboSwapPairs(
            record,
            direction,
        );
        return this.swapSections(movingRecords, targetRecords);
    }

    getComboSwapPairs(record, direction) {
        const comboRecords = getComboRecords(this.props.list.records, record);

        if (direction === "up") {
            return {
                movingRecords: this.getPreviousRecords(record),
                targetRecords: comboRecords,
            };
        }
        if (direction === "down") {
            return {
                movingRecords: comboRecords,
                targetRecords: this.getNextRecords(record),
            };
        }
        return { movingRecords: [], targetRecords: [] };
    }

    getPreviousRecords(record) {
        const { records } = this.props.list;
        const previousRecord = records[indexOfRecord(records, record) - 1];

        if (previousRecord?.data.combo_item_id?.id) {
            return getComboRecords(records, previousRecord);
        }
        return previousRecord ? [previousRecord] : false;
    }

    getNextRecords(record) {
        const { records } = this.props.list;
        const comboRecords = getComboRecords(records, record);

        const nextRecord =
            records[indexOfRecord(records, record) + comboRecords.length];
        if (nextRecord?.data.product_type === "combo") {
            return getComboRecords(records, nextRecord);
        }
        return nextRecord ? [nextRecord] : false;
    }

    canUseFormatter(column, record) {
        if (this.isCombo(record) && this.props.aggregatedFields.includes(column.name)) {
            return true;
        }
        return super.canUseFormatter(column, record);
    }

    getFormattedValue(column, record) {
        if (this.isCombo(record) && this.props.aggregatedFields.includes(column.name)) {
            const total = getComboRecords(this.props.list.records, record).reduce(
                (total, record) => total + record.data[column.name],
                0,
            );

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

    isCombo(record) {
        return record.data.product_type === "combo";
    }

    isComboItem(record) {
        return !!record.data.combo_item_id;
    }

    shouldDuplicateSectionItem(record) {
        return !this.isCombo(record) && !this.isComboItem(record);
    }

    displayDeleteIcon(record) {
        return super.displayDeleteIcon(record) && !this.isComboItem(record);
    }
}

export class SaleOrderLineOne2Many extends ProductLabelSectionAndNoteOne2Many {
    static components = {
        ...ProductLabelSectionAndNoteOne2Many.components,
        ListRenderer: SaleOrderLineListRenderer,
    };
}
export const saleOrderLineOne2Many = {
    ...productLabelSectionAndNoteOne2Many,
    component: SaleOrderLineOne2Many,
    additionalClasses: sectionAndNoteFieldOne2Many.additionalClasses,
};

registry.category("fields").add("sol_o2m", saleOrderLineOne2Many);

export class SaleOrderLineText extends SectionAndNoteText {
    get componentToUse() {
        return this.props.record.data.product_type === "combo"
            ? CharField
            : super.componentToUse;
    }
}

export class ListSaleOrderLineText extends ListSectionAndNoteText {
    get componentToUse() {
        return this.props.record.data.product_type === "combo"
            ? CharField
            : super.componentToUse;
    }
}

export const saleOrderLineText = {
    ...sectionAndNoteText,
    component: SaleOrderLineText,
};

export const listSaleOrderLineText = {
    ...listSectionAndNoteText,
    component: ListSaleOrderLineText,
};

registry.category("fields").add("sol_text", saleOrderLineText);
registry.category("fields").add("list.sol_text", listSaleOrderLineText);
