/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ProductTemplateAttributeLine } from "@sale/js/product_template_attribute_line/product_template_attribute_line";
import { patch } from "@web/core/utils/patch";

patch(ProductTemplateAttributeLine.prototype, {
    /**
     * @return {String}
     */
    getPtalDisplayName() {
        const selectedPtavIds = new Set(this.props.selected_attribute_value_ids);
        const selectedPtavNames = this.props.attribute_values
            .filter((ptav) => selectedPtavIds.has(ptav.id))
            .map((ptav) => ptav.name)
            .join(", ");
        let ptalDisplayName = `${this.props.attribute.name}: ${selectedPtavNames}`;
        if (this.isSelectedPTAVCustom()) {
            ptalDisplayName += `: ${this.props.customValue}`;
        }
        return ptalDisplayName;
    },

    get customValuePlaceholder() {
        return _t("Enter a customized value");
    },
});
