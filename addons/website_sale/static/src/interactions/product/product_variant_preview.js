/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class ProductVariantPreview extends Interaction {
    static selector = "#o_wsale_products_grid";

    dynamicContent = {
        _window: {
            "t-on-resize": this.debounced(this.updateVariantPreview, 250),
        },
    };

    setup() {
        this.margin = 4;
        this.updateVariantPreview();
    }

    /**
     * @private
     * @returns {void}
     */
    _resetDisplay(attributePreviewer) {
        for (const child of attributePreviewer.children) {
            child.classList.add("d-none");
        }
    }

    /**
     * @private
     * @param {Element} currentPTAV
     * @param {Number} remainingSpace
     * @returns {void}
     */
    _showHiddenPTAVsElement(
        attributePreviewerValues,
        currentPTAV,
        remainingSpace,
        displayedPTAVCount,
    ) {
        const { ptavCount, offsetWidthPTAVS, hiddenCountSpan, hiddenCountSpanWidth } =
            attributePreviewerValues;
        while (currentPTAV && hiddenCountSpanWidth >= remainingSpace) {
            currentPTAV.classList.add("d-none");
            displayedPTAVCount--;
            remainingSpace += offsetWidthPTAVS.get(currentPTAV);
            currentPTAV = currentPTAV.previousElementSibling;
        }
        const hiddenPTAVCount = ptavCount - displayedPTAVCount;
        hiddenCountSpan.firstElementChild.textContent = `+${hiddenPTAVCount}`;
        hiddenCountSpan.classList.remove("d-none");
    }

    /**
     * @private
     * @returns {void}
     */
    _updateVariantPreview(attributePreviewer, attributePreviewerValues) {
        const { containerWidth, ptavs, ptavCount, offsetWidthPTAVS } =
            attributePreviewerValues;
        this._resetDisplay(attributePreviewer);
        let usedWidth = 0;
        let displayedPTAVCount = 0;
        for (const ptav of ptavs) {
            ptav.classList.remove("d-none");
            usedWidth += offsetWidthPTAVS.get(ptav) + this.margin;
            displayedPTAVCount++;
            const remainingSpace = containerWidth - usedWidth;
            const isLastPTAV = ptav === ptavs[ptavs.length - 1];
            const hasHiddenPtavs = isLastPTAV && ptavCount > displayedPTAVCount;
            if (usedWidth >= containerWidth || hasHiddenPtavs) {
                this._showHiddenPTAVsElement(
                    attributePreviewerValues,
                    ptav,
                    remainingSpace,
                    displayedPTAVCount,
                );
                break;
            }
        }
    }

    updateVariantPreview() {
        const attributePreviewers = this.el.querySelectorAll(
            ".o_wsale_attribute_previewer",
        );
        const updateAllVariantPreview = this.bindDeferred(() => {
            const attributePreviewerValues = new Map();

            for (const attributePreviewer of attributePreviewers) {
                this._resetDisplay(attributePreviewer);
                const ptavs = attributePreviewer.querySelectorAll(
                    ".o_product_variant_preview",
                );
                const hiddenCountSpan = attributePreviewer.querySelector(
                    "span[name='hidden_ptavs_count']",
                );
                const ptavCount =
                    ptavs.length +
                    Number(attributePreviewer.dataset.hiddenPtavCount ?? 0);
                hiddenCountSpan.firstElementChild.textContent = `+${ptavCount}`;
                hiddenCountSpan.classList.remove("d-none");
                attributePreviewerValues.set(attributePreviewer, {
                    containerWidth: attributePreviewer.offsetWidth,
                    ptavs,
                    hiddenCountSpan,
                    ptavCount,
                    offsetWidthPTAVS: new Map(),
                    hiddenCountSpanWidth: 0,
                });
            }

            for (const attributePreviewer of attributePreviewers) {
                const currentValues = attributePreviewerValues.get(attributePreviewer);
                for (const ptav of currentValues.ptavs) {
                    ptav.classList.remove("d-none");
                }
            }

            for (const attributePreviewer of attributePreviewers) {
                const currentValues = attributePreviewerValues.get(attributePreviewer);
                for (const ptav of currentValues.ptavs) {
                    currentValues.offsetWidthPTAVS.set(ptav, ptav.offsetWidth);
                }
                currentValues.hiddenCountSpanWidth =
                    currentValues.hiddenCountSpan.offsetWidth + this.margin * 2;
            }

            for (const attributePreviewer of attributePreviewers) {
                this._updateVariantPreview(
                    attributePreviewer,
                    attributePreviewerValues.get(attributePreviewer),
                );
            }
        });
        requestAnimationFrame(updateAllVariantPreview);
    }
}

registry
    .category("public.interactions")
    .add("website_sale.product_variant_preview", ProductVariantPreview);

registry
    .category("public.interactions.edit")
    .add("website.product_variant_preview", { Interaction: ProductVariantPreview });
