/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { SIZES, utils } from "@web/ui/viewport";
patch(utils, {
    isSmall(ui = {}) {
        return (ui.size || utils.getSize()) <= SIZES.MD;
    },
});
