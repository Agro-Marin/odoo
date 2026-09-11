/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { redirect } from "@web/core/utils/urls";
import { Interaction } from "@web/public/interaction";

export class SaleOrderPortalReorder extends Interaction {
    static selector = "#sale_order_sidebar_button";
    dynamicContent = {
        "button#reorder_sidebar_button": { "t-on-click": this.onReorder },
    };

    /**
     * @param {Event} ev
     */
    async onReorder(ev) {
        this.orderId = parseInt(ev.currentTarget.dataset.saleOrderId);
        this.accessToken = new URLSearchParams(window.location.search).get(
            "access_token",
        );
        if (!this.orderId) return;

        await this._doReorder();
    }

    async _doReorder() {
        try {
            const values = await this.waitFor(
                rpc("/my/orders/reorder", {
                    order_id: this.orderId,
                    access_token: this.accessToken,
                }),
            );

            browser.sessionStorage.setItem(
                "website_sale_cart_quantity",
                values.cart_quantity,
            );

            this._trackProducts(values.tracking_info);
            redirect("/shop/cart");
        } catch (error) {
            console.error("Error during reordering:", error);
        }
    }

    /**
     * @private
     * @param {Object[]} trackingInfo
     * @returns {void}
     */
    _trackProducts(trackingInfo) {
        document
            .querySelector(".oe_website_sale")
            .dispatchEvent(
                new CustomEvent("add_to_cart_event", { detail: trackingInfo }),
            );
    }
}

registry
    .category("public.interactions")
    .add("website_sale.portal_reorder", SaleOrderPortalReorder);
