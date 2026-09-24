/** @odoo-module native */
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.utils = useService("contextual_utils_service");
    },

    async clickDiscount() {
        this.dialog.add(NumberPopup, {
            title: _t("Discount Percentage"),
            startingValue: this.pos.config.discount_pc,
            getPayload: (num) => {
                const percent = Math.max(
                    0,
                    Math.min(100, this.utils.parseValidFloat(num.toString())),
                );
                this.applyDiscount(percent);
            },
        });
    },
    // FIXME business method in a compoenent, maybe to move in pos_store
    async applyDiscount(percent) {
        return this.pos.applyDiscount(percent);
    },
});
