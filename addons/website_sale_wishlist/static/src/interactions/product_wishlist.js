/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { redirect } from "@web/core/utils/urls";
import { Interaction } from "@web/public/interaction";
import wishlistUtils from "@website_sale_wishlist/js/website_sale_wishlist_utils";

export class ProductWishlist extends Interaction {
    static selector = ".wishlist-section";
    dynamicContent = {
        ".o_wish_rm": { "t-on-click": this.removeProduct },
        ".o_wish_add": { "t-on-click": this.addToCart },
    };

    /**
     * @param {Event} ev
     */
    async removeProduct(ev) {
        await this._removeProduct(ev.currentTarget);
    }

    /**
     * @param {Event} ev
     */
    async addToCart(ev) {
        const button = ev.currentTarget;
        const productId = parseInt(button.dataset.productProductId);
        const productTemplateId = parseInt(button.dataset.productTemplateId);
        const isCombo = button.dataset.productType === "combo";
        const ptavs = JSON.parse(button.dataset.ptavIds || "[]");
        const showQuantity = Boolean(button.dataset.showQuantity);

        const quantity = await this.waitFor(
            this.services["cart"].add(
                {
                    productTemplateId: productTemplateId,
                    productId: productId,
                    isCombo: isCombo,
                    ptavs: ptavs,
                },
                {
                    isConfigured: false,
                    redirectToCart: false,
                    showQuantity: showQuantity,
                },
            ),
        );

        if (quantity > 0) {
            await this._removeProduct(button, "/shop/cart");
        }
    }

    /**
     * @param {Element} button
     * @param {String} emptyRedirectUrl
     */
    async _removeProduct(button, emptyRedirectUrl) {
        const article = button.closest("article");
        const wish = article.dataset.wishId;
        const productId = parseInt(article.dataset.productId);

        await this.waitFor(rpc(`/shop/wishlist/remove/${wish}`));
        article.style.display = "none";

        wishlistUtils.removeWishlistProduct(productId);
        wishlistUtils.updateWishlistView();
        if (!wishlistUtils.getWishlistProductIds().length && emptyRedirectUrl) {
            redirect(emptyRedirectUrl);
        }
        wishlistUtils.updateWishlistNavBar();
    }
}

registry
    .category("public.interactions")
    .add("website_sale_wishlist.product_wishlist", ProductWishlist);
