/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { CourseJoinBehavior } from "@website_slides/interactions/course_join";

patch(CourseJoinBehavior.prototype, {
    setup(options) {
        super.setup(options);
        this.productId = options.channel.productId || false;
    },

    /**
     * When the user joins the course, if it's set as "on payment" and the
     * user is logged in, we redirect to the shop page for this course.
     *
     * @param {MouseEvent} ev
     * @override
     */
    _onClickJoin(ev) {
        ev.preventDefault();

        if (this.channel.channelEnroll === "payment" && !this.publicUser) {
            this.beforeJoin().then(() => {
                this.host.services.cart.add(
                    {
                        // TODO VCR Ensure productTemplateId is always provided to `addToCart`.
                        // Currently, this works because the product configurator check is bypassed
                        // when the `isBuyNow` option is `True`.
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
