/** @odoo-module native */
import {
    SectionAndNoteFieldOne2Many,
    sectionAndNoteFieldOne2Many,
    SectionAndNoteListRenderer,
} from "@account/components/section_and_note_fields_backend/section_and_note_fields_backend";
import { ProductNameAndDescriptionListRendererMixin } from "@product/product_name_and_description/product_name_and_description";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

export class ProductLabelSectionAndNoteListRender extends SectionAndNoteListRenderer {
    setup() {
        super.setup();
        this.descriptionColumn = "name";
        this.productColumns = ["product_id", "product_template_id"];
        this.conditionalColumns = ["product_id", "quantity", "product_uom_id"];
    }

    processAllColumns(allColumns, list) {
        allColumns = allColumns.map((column) => {
            // Gate on the column name, not column.optional: the base re-invokes this
            // every render against the SAME cached arch objects, so mutating
            // column.optional in place made the "conditional" gate fail after the
            // first render and let one move_type's visibility leak to other invoices.
            // Recompute from the current move_type into a shallow copy each time.
            if (!this.conditionalColumns.includes(column["name"])) {
                return column;
            }
            /**
             * The preference should be different whether:
             *     - It's a Vendor Bill or an Invoice
             *     - Sale module is installed
             * Vendor Bills -> Product should be hidden by default
             * Invoices -> conditionalColumns should be hidden by default if Sale module is not installed
             */
            const isBill = ["in_invoice", "in_refund", "in_receipt"].includes(this.props.list.evalContext.parent.move_type);
            const isInvoice = ["out_invoice", "out_refund", "out_receipt"].includes(this.props.list.evalContext.parent.move_type);
            const isSaleInstalled = this.props.list.evalContext.parent.is_sale_installed;
            let optional = "show";
            if (isBill && column["name"] === "product_id") {
                optional = "hide";
            }
            else if (isInvoice && !isSaleInstalled) {
                optional = "hide";
            }
            return { ...column, optional };
        });
        return super.processAllColumns(allColumns, list);
    }

    isCellReadonly(column, record) {
        if (![...this.productColumns, "name"].includes(column.name)) {
            return super.isCellReadonly(column, record);
        }
        // The isCellReadonly method from the ListRenderer is used to determine the classes to apply to the cell.
        // We need this override to make sure some readonly classes are not applied to the cell if it is still editable.
        let isReadonly = super.isCellReadonly(column, record);
        return (
            isReadonly
            && (["cancel", "posted"].includes(record.evalContext.parent.state)
            || record.evalContext.parent.locked)
        )
    }
}

patch(ProductLabelSectionAndNoteListRender.prototype, ProductNameAndDescriptionListRendererMixin());

export class ProductLabelSectionAndNoteOne2Many extends SectionAndNoteFieldOne2Many {
    static components = {
        ...super.components,
        ListRenderer: ProductLabelSectionAndNoteListRender,
    };
}

export const productLabelSectionAndNoteOne2Many = {
    ...sectionAndNoteFieldOne2Many,
    component: ProductLabelSectionAndNoteOne2Many,
};

registry
    .category("fields")
    .add("product_label_section_and_note_field_o2m", productLabelSectionAndNoteOne2Many);
