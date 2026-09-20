/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { CourseJoinBehavior } from "@website_slides/interactions/course_join";

patch(CourseJoinBehavior.prototype, {
    setup(options) {
        super.setup(options);
        this.productId = options.channel.productId || false;
    },

    /**
     * @param {MouseEvent} ev
     * @override
     */
    _onClickJoin(ev) {
        ev.preventDefault();

        if (this.channel.channelEnroll === "payment" && !this.publicUser) {
            this.beforeJoin().then(() => {
                this.host.services.cart.add(
                    {
                        productTemplateId: false,
                        productId: this.productId,
                    },
                    {
                        isBuyNow: true,
                    },
                );
            });
        } else {
            super._onClickJoin(...arguments);
        }
    },
});
