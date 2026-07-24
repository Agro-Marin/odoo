/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { QuizNoFullscreen } from "@website_slides/interactions/quiz";

patch(QuizNoFullscreen.prototype, {
    _extractChannelData(slideData) {
        return Object.assign({}, super._extractChannelData(...arguments), {
            productId: slideData.productId,
            enroll: slideData.enroll,
            currencyName: slideData.currencyName,
            currencySymbol: slideData.currencySymbol,
            price: slideData.price,
            hasDiscountedPrice: slideData.hasDiscountedPrice,
        });
    },
});
