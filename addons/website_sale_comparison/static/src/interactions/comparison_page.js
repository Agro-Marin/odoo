/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import comparisonUtils from "@website_sale_comparison/js/website_sale_comparison_utils";
import { redirect } from "@web/core/utils/urls";

export class ComparisonPage extends Interaction {
    static selector = "#o_comparelist_table";

    dynamicSelectors = {
        ...this.dynamicSelectors,
        _miniSticky: () => document.querySelector("#miniStickyComparison"),
        _mainScroll: () =>
            document.querySelector(".table-comparator")?.closest(".overflow-x-auto"),
        _miniScroll: () =>
            document.querySelector("#miniStickyComparison .overflow-x-auto"),
        _backButton: () =>
            document.querySelector('button[name="comparison_back_button"]'),
        _clearAllButton: () =>
            document.querySelector('button[name="comparison_clear_all_button"]'),
    };

    dynamicContent = {
        'button[name="comparison_add_to_cart"]': { "t-on-click": this.addToCart },
        ".o_comparelist_remove": { "t-on-click": this.removeProduct },
        _backButton: { "t-on-click": () => redirect("/shop") },
        _clearAllButton: { "t-on-click": this.clearAllProducts },
    };

    setup() {
        this.position = 0;
    }

    start() {
        this._adaptToHeaderChange();
        this.registerCleanup(
            this.services.website_menus.registerCallback(
                this._adaptToHeaderChange.bind(this),
            ),
        );
        this._initMiniStickyComparison();
    }

    /**
     * @private
     */
    _adaptToHeaderChange() {
        let position = 0;

        for (const el of this.el.ownerDocument.querySelectorAll(
            ".o_top_fixed_element",
        )) {
            position += el.offsetHeight;
        }

        if (this.position !== position) {
            this.position = position;
            this.updateContent();

            const miniStickyEl = this.dynamicSelectors._miniSticky();
            if (miniStickyEl) {
                miniStickyEl.style.top = `${position}px`;
            }
        }
    }

    clearAllProducts() {
        comparisonUtils.clearComparisonProducts(this.bus);
        redirect("/shop");
    }

    /**
     * @private
     */
    _initMiniStickyComparison() {
        const miniStickyEl = this.dynamicSelectors._miniSticky();
        const productImagesEl = this.el.querySelector("ul:first-of-type");

        if (!miniStickyEl || !productImagesEl) return;

        miniStickyEl.style.top = `${this.position}px`;

        const mainScrollEl = this.dynamicSelectors._mainScroll();
        const miniScrollEl = this.dynamicSelectors._miniScroll();

        const handleVerticalScroll = () => {
            const rect = productImagesEl.getBoundingClientRect();
            const shouldShow = rect.bottom < this.position + 20;

            miniStickyEl.classList.toggle("show", shouldShow);
            miniStickyEl.classList.toggle("d-none", !shouldShow);

            if (shouldShow && mainScrollEl && miniScrollEl) {
                miniScrollEl.scrollLeft = mainScrollEl.scrollLeft;
            }
        };

        const syncScroll = (source, target) => {
            if (!source._syncing) {
                target._syncing = true;
                target.scrollLeft = source.scrollLeft;
                requestAnimationFrame(() => (target._syncing = false));
            }
        };

        window.addEventListener("scroll", handleVerticalScroll, { passive: true });
        if (mainScrollEl && miniScrollEl) {
            mainScrollEl.addEventListener(
                "scroll",
                () => syncScroll(mainScrollEl, miniScrollEl),
                { passive: true },
            );
            miniScrollEl.addEventListener(
                "scroll",
                () => syncScroll(miniScrollEl, mainScrollEl),
                { passive: true },
            );
        }

        this.registerCleanup(() => {
            window.removeEventListener("scroll", handleVerticalScroll);
        });

        handleVerticalScroll();
    }

    /**
     * @param {Event} ev
     */
    addToCart(ev) {
        const button = ev.currentTarget;
        const productId = parseInt(button.dataset.productProductId);
        const productTemplateId = parseInt(button.dataset.productTemplateId);
        const showQuantity = Boolean(button.dataset.showQuantity);

        this.services["cart"].add(
            {
                productTemplateId: productTemplateId,
                productId: productId,
            },
            {
                showQuantity: showQuantity,
            },
        );
    }

    /**
     * @param {Event} ev
     */
    removeProduct(ev) {
        const productId = parseInt(ev.currentTarget.dataset.productProductId);
        comparisonUtils.removeComparisonProduct(productId, null);

        const productIds = comparisonUtils.getComparisonProductIds();
        if (productIds.length === 0) {
            redirect("/shop");
        } else {
            const comparisonUrl = `/shop/compare?products=${encodeURIComponent(productIds.join(","))}`;
            redirect(comparisonUrl);
        }
    }
}

registry
    .category("public.interactions")
    .add("website_sale_comparison.comparison_page", ComparisonPage);
