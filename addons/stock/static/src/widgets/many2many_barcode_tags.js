/** @odoo-module native */
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags/many2many_tags_field";
import { registry } from "@web/core/registry";
import { RPCError } from "@web/core/network/rpc";

export class Many2XBarcodeTagsAutocomplete extends Many2XAutocomplete {
    onQuickCreateError(error, request) {
        // A duplicate barcode surfaces as a ValidationError (the `unique(barcode)`
        // constraint or the product-barcode check). Raise it to show the error dialog
        // instead of the slow-create dialog, which can't resolve a barcode conflict.
        // Detect via the RPC exception name, not `error.data.debug`: the server hides
        // tracebacks outside dev mode, so that text isn't reliably available.
        if (
            error instanceof RPCError &&
            error.exceptionName === "odoo.exceptions.ValidationError"
        ) {
            throw error;
        }
        super.onQuickCreateError(error, request);
    }
}

export class Many2ManyBarcodeTagsField extends Many2ManyTagsField {
    static components = {
        ...Many2ManyTagsField.components,
        Many2XAutocomplete: Many2XBarcodeTagsAutocomplete,
    };
}

export const many2ManyBarcodeTagsField = {
    ...many2ManyTagsField,
    component: Many2ManyBarcodeTagsField,
    additionalClasses: ['o_field_many2many_tags'],
}

registry.category("fields").add("many2many_barcode_tags", many2ManyBarcodeTagsField);
