/** @odoo-module native */
import { onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { deepCopy } from "@web/core/utils/collections/objects";
import { useService } from "@web/core/utils/hooks";
import { RadioField, radioField } from "@web/fields/selection/radio/radio_field";

const labels = {
    in_invoice: _t("Bill"),
    out_invoice: _t("Invoice"),
    in_receipt: _t("Receipt"),
    out_receipt: _t("Receipt"),
};

const in_move_types = ["in_invoice", "in_receipt"];
const out_move_types = ["out_invoice", "out_receipt"];

export class ReceiptSelector extends RadioField {
    static template = "account.ReceiptSelector";
    static props = {
        ...RadioField.props,
    };

    setup() {
        super.setup();
        this.lazySession = useService("lazy_session");
        this.show_sale_receipts = useState({ value: false });
        onWillStart(() => {
            this.lazySession.getValue("show_sale_receipts", (show_sale_receipts) => {
                this.show_sale_receipts.value = show_sale_receipts;
            });
        });
    }

    /**
     * Remove the unwanted options and relabel the remaining ones.
     * @override
     */
    get items() {
        const original_items = super.items;
        if (this.type !== "selection") {
            return original_items;
        }

        // Use a copy to avoid updating the original selection labels
        let items = deepCopy(original_items);

        let allowedValues = [];
        if (in_move_types.includes(this.value)) {
            allowedValues = in_move_types;
        } else if (
            out_move_types.includes(this.value) &&
            this.show_sale_receipts.value
        ) {
            allowedValues = out_move_types;
        }

        if (allowedValues.length > 1) {
            items = items.filter((item) => allowedValues.includes(item[0]));

            items.forEach((item) => {
                if (item[0] in labels) {
                    item[1] = labels[item[0]];
                }
            });
        }
        return items;
    }

    get string() {
        if (this.type === "selection") {
            // Use the original labels and not the modified ones
            return this.value !== false
                ? (this.props.record.fields[this.props.name].selection.find(
                      (i) => i[0] === this.value,
                  )?.[1] ?? "")
                : "";
        }
        return "";
    }
}

export const receiptSelector = {
    ...radioField,
    additionalClasses: ["o_field_radio"],
    component: ReceiptSelector,
};

registry.category("fields").add("receipt_selector", receiptSelector);
