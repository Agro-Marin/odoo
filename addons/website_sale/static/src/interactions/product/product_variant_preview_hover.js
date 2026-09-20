/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class ProductVariantPreviewImageHover extends Interaction {
    static selector = ".oe_product_cart.o_has_variations";
    dynamicContent = {
        ".o_product_variant_preview": {
            "t-on-mouseenter": this._mouseEnter,
            "t-on-mouseleave": this._mouseLeave,
            "t-on-click": this._onClick,
        },
    };

    setup() {
        this.productImg = this.el.querySelector(
            ".oe_product_image_img_wrapper_primary img",
        );
        this.originalImgSrc = this.productImg.getAttribute("src");
    }

    /**
     * @private
     * @param {Event} ev
     * @returns {void}
     */
    _mouseEnter(ev) {
        if (!this.env.isSmall) {
            const variantImageSrc = ev.target.dataset.variantImage;
            if (!variantImageSrc) {
                return;
            }
            this._setImgSrc(variantImageSrc);
        }
    }

    /**
     * @private
     * @returns {void}
     */
    _mouseLeave() {
        if (!this.env.isSmall) {
            this._setImgSrc(this.originalImgSrc);
        }
    }

    /**
     * @param {string} imageSrc
     */
    _setImgSrc(imageSrc) {
        this.productImg.src = imageSrc;
    }

    /**
     * @param {Event} ev
     */
    _onClick(ev) {
        if (this.env.isSmall) {
            ev.preventDefault();
            const targetElement = ev.target.closest(".o_product_variant_preview");
            const productCard = ev.target.closest(".oe_product_cart");
            productCard.querySelector(".oe_product_image_link").href =
                targetElement.href;
            const variantImageSrc = targetElement.dataset.variantImage;
            if (!variantImageSrc) {
                return;
            }
            this._setImgSrc(variantImageSrc);
        }
    }
}

registry
    .category("public.interactions")
    .add(
        "website_sale.product_variant_preview_image_hover",
        ProductVariantPreviewImageHover,
    );
