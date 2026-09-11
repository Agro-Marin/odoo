// @ts-check
/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";
/** @type {Partial<import("models").Store> & ThisType<import("models").Store>} */
const StorePatch = {
    setup() {
        super.setup();
        this.hasGifPickerFeature = false;
    },
};
patch(Store.prototype, StorePatch);
