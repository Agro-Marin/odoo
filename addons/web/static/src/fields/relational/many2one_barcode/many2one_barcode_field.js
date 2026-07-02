// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2one_barcode/many2one_barcode_field - Many2one field with barcode scanner support */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import {
    buildM2OFieldDescription,
    extractM2OFieldProps,
    Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";

export class Many2OneBarcodeField extends Many2OneField {
    static template = "web.Many2OneBarcodeField";
}

registerField("many2one_barcode", {
    ...buildM2OFieldDescription(Many2OneBarcodeField),
    displayName: _t("Many2OneBarcode"),
    extractProps(staticInfo, dynamicInfo) {
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            canScanBarcode: true,
        };
    },
});
