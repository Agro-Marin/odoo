/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Dropdown } from "@web/libs/bootstrap";
import { BaseHeader } from "@website/interactions/header/base_header";

const log = makeLogger("website.interaction.base_header_special");

export class BaseHeaderSpecial extends BaseHeader {
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _searchbar: () => this.searchbarEl,
    };
    dynamicContent = {
        ...this.dynamicContent,
        ".o_header_hide_on_scroll .dropdown-toggle": {
            "t-on-show.bs.dropdown": this.onDropdownShow,
        },
        _searchbar: {
            "t-on-input": this.onSearchbarInput,
        },
    };

    setup() {
        super.setup();
        this.isAnimated = false;

        this.position = 0;
        this.checkpoint = 0;
        this.scrollOffset = 200;
        this.scrollingDownward = true;

        this.searchbarEl = this.hideEl?.querySelector(
            ":not(.modal-content) > .o_searchbar_form",
        );
        this.dropdownClickedEl = null;
    }

    /**
     * @param {Event} ev
     */
    onDropdownShow(ev) {
        if (this.cssAffixed) {
            log.logic(
                "BaseHeaderSpecial onDropdownShow: affixed, scroll to top first",
                () => ({
                    toggle: ev.currentTarget.className,
                }),
            );
            ev.preventDefault();
            this.scrollingElement.scrollTo({ top: 0, behavior: "smooth" });
            this.dropdownClickedEl = ev.currentTarget;
        }
    }

    onSearchbarInput() {
        if (this.cssAffixed) {
            this.scrollingElement.scroll({ top: 0 });
        }
    }

    onScroll() {
        super.onScroll();

        const scroll = this.scrollingElement.scrollTop;

        this.atTop = scroll <= this.topGap;
        this.isScrolled = scroll > this.topGap;

        if (scroll > this.topGap) {
            if (!this.cssAffixed) {
                log.logic("BaseHeaderSpecial onScroll: affix", () => ({
                    interaction: this.constructor.name,
                    scroll,
                    topGap: this.topGap,
                }));
                this.transformShow();
                void this.el.offsetWidth;
                this.toggleCSSAffixed(true);
            }
        } else {
            this.transformShow();
            void this.el.offsetWidth;
            this.toggleCSSAffixed(false);
        }

        if (this.hideEl) {
            this.hideEl.style.height = "";
            this.hideEl.classList.remove("hidden");
            let elHeight;
            if (this.cssAffixed) {
                this.hideEl
                    .querySelectorAll(".dropdown-toggle.show")
                    .forEach((dropdownToggleEl) => {
                        Dropdown.getOrCreateInstance(dropdownToggleEl).hide();
                    });
                elHeight = this.hideEl.offsetHeight;
            } else {
                elHeight = this.hideEl.scrollHeight;
            }
            const scrollDelta = window.matchMedia(`(prefers-reduced-motion: reduce)`)
                .matches
                ? scroll
                : Math.floor(scroll / 4);
            elHeight = Math.max(0, elHeight - scrollDelta);
            this.hideEl.classList.toggle("hidden", elHeight === 0);
            if (elHeight === 0) {
                this.hideEl.removeAttribute("style");
            } else {
                this.hideEl.style.overflow = this.cssAffixed ? "hidden" : "";
                this.hideEl.style.height = this.cssAffixed ? `${elHeight}px` : "";
                let elPadding = parseInt(getComputedStyle(this.hideEl).paddingBlock);
                if (elHeight < elPadding * 2) {
                    const heightDifference = elPadding * 2 - elHeight;
                    elPadding = Math.max(
                        0,
                        elPadding - Math.floor(heightDifference / 2),
                    );
                    this.hideEl.style.setProperty(
                        "padding-block",
                        `${elPadding}px`,
                        "important",
                    );
                } else {
                    this.hideEl.style.paddingBlock = "";
                }
            }
            this.adaptToHeaderChange();
        }

        if (!this.cssAffixed && this.dropdownClickedEl) {
            log.logic(
                "BaseHeaderSpecial onScroll: reopen dropdown clicked while affixed",
                () => ({
                    isConnected: this.dropdownClickedEl.isConnected,
                }),
            );
            if (this.dropdownClickedEl.isConnected) {
                Dropdown.getOrCreateInstance(this.dropdownClickedEl).show();
            }
            this.dropdownClickedEl = null;
        }

        if (this.isAnimated && this.transitionActive) {
            const scrollingDownward = scroll > this.position;
            this.position = scroll;
            if (this.scrollingDownward !== scrollingDownward) {
                log.logic("BaseHeaderSpecial onScroll: direction changed", () => ({
                    interaction: this.constructor.name,
                    scrollingDownward,
                    checkpoint: scroll,
                }));
                this.checkpoint = scroll;
            }
            this.scrollingDownward = scrollingDownward;

            if (scrollingDownward) {
                const movement = this.position - this.checkpoint;
                if (this.isVisible && movement > this.scrollOffset + this.topGap) {
                    log.pipeline(
                        "BaseHeaderSpecial onScroll: visible -> hidden",
                        () => ({
                            interaction: this.constructor.name,
                            movement,
                            position: this.position,
                        }),
                    );
                    this.transformHide();
                }
            } else {
                const movement = this.checkpoint - this.position;
                if (
                    !this.isVisible &&
                    movement > (this.scrollOffset + this.topGap) / 2
                ) {
                    log.pipeline(
                        "BaseHeaderSpecial onScroll: hidden -> visible",
                        () => ({
                            interaction: this.constructor.name,
                            movement,
                            position: this.position,
                        }),
                    );
                    this.transformShow();
                }
            }
        }
    }
}

registry.category("public.interactions.edit").add("website.base_header_special", {
    Interaction: BaseHeaderSpecial,
    isAbstract: true,
});
