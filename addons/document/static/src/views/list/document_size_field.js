/** @odoo-module native */
import { humanSize } from "@web/core/utils/format/binary";
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";
import { IntegerField } from "@web/fields/basic/integer/integer_field";

export class DocumentSizeIntegerField extends IntegerField {
    get formattedValue() {
        if (!this.value) {
            return "";
        }
        return humanSize(this.value);
    }
}

const documentSizeIntegerField = {
    component: DocumentSizeIntegerField,
    displayName: _t("DocumentSizeIntegerField"),
    supportedTypes: ["integer"],
};

registry.category("fields").add("document_size", documentSizeIntegerField);
