/** @odoo-module native */

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class ProductGridLayout extends Interaction {
    static selector = "#o-grid-product";

    dynamicContent = {
        _window: {
            "t-on-resize": this.debounced(this.onResize, 100),
        },
        _root: {
            "t-att-class": () => ({
                o_grid_product_ready: this.isGridReady,
            }),
            "t-att-style": () => ({
                "--o-wsale-js-grid-product-height": this.gridHeight || "auto",
            }),
        },
    };

    setup() {
        this.gridHeight = null;
        this.maxHeight = 0;
        this.isGridReady = false;
        this.loadedImages = new Set();

        this.imagesEls = this.el.querySelectorAll(".product_detail_img");
        this.isAutoRatioMode =
            this.el.classList.contains("o_grid_uses_ratio_auto") &&
            this.el.classList.contains("o_grid_uses_ratio_mobile_auto");
    }

    start() {
        if (this.imagesEls.length === 0) {
            return;
        }

        if (this.imagesEls.length === 1 || !this.isAutoRatioMode) {
            this.handleStandardMode();
        } else {
            this.handleAutoRatioMode();
        }

        this.updateContent();
    }

    handleStandardMode() {
        const firstImage = this.imagesEls[0];

        if (firstImage.complete && firstImage.naturalHeight !== 0) {
            this.calculateImageHeight();
        } else {
            this.addListener(firstImage, "load", this.calculateImageHeight);
        }
    }

    calculateImageHeight() {
        const firstImage = this.imagesEls[0];
        if (!firstImage) return;

        const height = firstImage.offsetHeight;
        this.isGridReady = Boolean(height);
        this.gridHeight = height ? `${height}px` : null;
    }

    handleAutoRatioMode() {
        const timeoutId = this.waitForTimeout(() => {
            this.finalizeAutoRatioCalculation();
        }, 5000);

        this.imagesEls.forEach((imgEl) => {
            if (imgEl.complete && imgEl.naturalHeight !== 0) {
                this.processLoadedImage(imgEl);
            } else {
                this.addListener(imgEl, "load", () => {
                    this.processLoadedImage(imgEl);

                    if (this.loadedImages.size === this.imagesEls.length) {
                        clearTimeout(timeoutId);
                        this.finalizeAutoRatioCalculation();
                    }
                });
            }
        });

        if (this.loadedImages.size === this.imagesEls.length) {
            clearTimeout(timeoutId);
            this.finalizeAutoRatioCalculation();
        }
    }

    processLoadedImage(imgEl) {
        this.loadedImages.add(imgEl);
        const height = imgEl.offsetHeight;
        if (height > this.maxHeight) {
            this.maxHeight = height;
        }
    }

    finalizeAutoRatioCalculation() {
        this.isGridReady = true;
        this.gridHeight = this.maxHeight ? `${this.maxHeight}px` : null;
    }

    onResize() {
        if (!this.env.isSmall) {
            return;
        }

        if (this.isAutoRatioMode) {
            this.maxHeight = 0;
            this.loadedImages.forEach((imgEl) => {
                const height = imgEl.offsetHeight;
                if (height > this.maxHeight) {
                    this.maxHeight = height;
                }
            });
            this.gridHeight = this.maxHeight ? `${this.maxHeight}px` : null;
        } else {
            this.calculateImageHeight();
        }
    }
}

registry
    .category("public.interactions")
    .add("website.website_sale_product_grid_layout", ProductGridLayout);

registry
    .category("public.interactions.edit")
    .add("website.website_sale_product_grid_layout", {
        Interaction: ProductGridLayout,
    });
