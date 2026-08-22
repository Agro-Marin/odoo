/** @odoo-module native */

import { Component, onPatched, useExternalListener, useRef, useState } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { _t } from "@web/core/translation";
import { useInputField } from "@web/fields/input_field_hook";
import {
    computeM2OProps,
    Many2One,
    Many2OneField,
} from "@web/fields/relational/many2one";

import { useProductAndLabelAutoresize } from "./product_and_label_autoresize.js";

// Factory: patch() mutates its extension to build the `super` chain, so each
// list renderer it is applied to needs its own fresh object.
export const ProductNameAndDescriptionListRendererMixin = () => ({
    getCellTitle(column, record) {
        // When using this list renderer, we don't want the product_id cell to have a tooltip with its label.
        if (this.productColumns.includes(column.name)) {
            return;
        }
        return super.getCellTitle(column, record);
    },

    getActiveColumns() {
        let activeColumns = super.getActiveColumns();
        const productCol = activeColumns.find((col) =>
            this.productColumns.includes(col.name),
        );
        const labelCol = activeColumns.find(
            (col) => col.name === this.descriptionColumn,
        );

        // Whether product and label share one cell is a property of the column
        // layout, not of any record: it is passed to the field through
        // `getFieldProps` rather than stamped onto every record on every render.
        this.columnIsProductAndLabel = Boolean(productCol && labelCol);
        if (productCol) {
            activeColumns = activeColumns.filter(
                (col) => col.name !== this.descriptionColumn,
            );
            this.titleField = productCol.name;
        } else {
            this.titleField = "name";
        }

        return activeColumns;
    },

    getFieldProps(record, column) {
        const props = super.getFieldProps(record, column);
        if (this.productColumns.includes(column.name)) {
            props.columnIsProductAndLabel = Boolean(this.columnIsProductAndLabel);
        }
        return props;
    },
});

export class ProductNameAndDescriptionField extends Component {
    static components = { Many2One };
    static props = {
        ...Many2OneField.props,
        columnIsProductAndLabel: { type: Boolean, optional: true },
    };
    static template = Many2One.template;

    static descriptionColumn = "";

    setup() {
        this.isPrintMode = useState({ value: false });
        this.labelVisibility = useState({ value: false });
        this.switchToLabel = false;
        this.labelNode = useRef("labelNodeRef");
        useProductAndLabelAutoresize(this.labelNode, {
            targetParentName: this.props.name,
        });
        this.productNode = useRef("productNodeRef");
        useProductAndLabelAutoresize(this.productNode, {
            targetParentName: this.props.name,
        });

        this.descriptionColumn = this.constructor.descriptionColumn;
        useInputField({
            ref: this.labelNode,
            fieldName: this.descriptionColumn,
            getValue: () => this.label,
            parse: (v) => this.parseLabel(v),
        });

        onPatched(() => {
            if (this.labelNode.el && this.switchToLabel) {
                this.switchToLabel = false;
                this.labelNode.el.focus();
            }
        });

        // The following listeners are used to make a div visible only in the print view. This div
        // is necessary in the print view in order not to have scroll bars but can't be displayed in
        // the normal view because it adds an empty line. This is done by switching an attribute to
        // true only during the print view life cycle and including the said div in a t-if depending
        // on that attribute.
        useExternalListener(window, "beforeprint", () => {
            this.isPrintMode.value = true;
        });
        useExternalListener(window, "afterprint", () => {
            this.isPrintMode.value = false;
        });
    }

    get columnIsProductAndLabel() {
        return Boolean(this.props.columnIsProductAndLabel);
    }

    get productName() {
        return this.props.record.data[this.props.name]?.display_name || "";
    }

    get label() {
        const stored = this.props.record.data[this.descriptionColumn] || "";
        // The description is *written* as `productName` followed by the user's
        // own text (see `parseLabel`), so only a leading occurrence is the
        // product name. An unanchored strip also eats the name where the user
        // typed it, turning "Spare leg for a Desk" into "Spare leg for a".
        const label = stored.startsWith(this.productName)
            ? stored.slice(this.productName.length)
            : stored;
        return label.trim();
    }

    get m2oProps() {
        const p = computeM2OProps(this.props);
        let value = p.value && { ...p.value };
        if (this.props.readonly && this.productName) {
            value = { ...value, display_name: this.productName };
        }
        return {
            ...p,
            canOpen: !this.props.readonly || this.isProductClickable,
            placeholder: _t("Search a product"),
            // product.product name_search ORs in a barcode match, so a
            // longer term can find what a shorter one did not -- no empty
            // search here may be skipped.
            searchMemoization: "none",
            value,
        };
    }

    /**
     * Whether the product may be opened from a read-only cell.
     *
     * The rule below is the one the order models this widget serves happen to
     * share; a consumer whose workflow differs overrides this. `parent` is
     * absent whenever the record is not inside an x2many, which must not throw.
     */
    get isProductClickable() {
        return this.props.record.evalContext.parent?.state !== "draft";
    }

    get showLabelVisibilityToggler() {
        return !this.props.readonly && this.columnIsProductAndLabel && !this.label;
    }

    switchLabelVisibility() {
        this.labelVisibility.value = !this.labelVisibility.value;
        this.switchToLabel = true;
    }

    parseLabel(value) {
        return value || this.productName;
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onM2oInputKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey === "enter" && this.showLabelVisibilityToggler) {
            this.switchLabelVisibility();
            ev.stopPropagation();
            ev.preventDefault();
        }
    }
}
