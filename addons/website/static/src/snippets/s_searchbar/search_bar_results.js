/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { isBrowserSafari } from "@web/core/browser/feature_detection";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { verifyHttpsUrl } from "@website/utils/misc";

const log = makeLogger("website.snippet.s_searchbar.results");

export class SearchBarResults extends Interaction {
    static selector = ".o_searchbar_form .o_dropdown_menu";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _scrollingParent: () => this.scrollingParentEl,
        _searchbar: () => this.searchBarEl,
    };
    dynamicContent = {
        _root: {
            "t-att-style": () => {
                const bcr = this.searchBarEl.getBoundingClientRect();
                return {
                    position: "absolute !important",
                    "max-width": `${bcr.width}px !important`,
                    "max-height": `max(40vh, ${
                        document.body.clientHeight - bcr.bottom - 16
                    }px) !important`,
                    "min-width": this.autocompleteMinWidth,
                };
            },
            "t-att-class": () => ({
                show: true,
            }),
            "t-att-data-bs-popper": () => (this.isDropup ? "" : undefined),
        },
        _searchbar: {
            "t-att-class": () => ({
                dropup: this.isDropup,
            }),
        },
        _window: {
            "t-on-resize": () => {},
        },
        _scrollingParent: {
            "t-on-scroll": () => {},
        },
        ".dropdown-item": {
            "t-on-mousedown": this.onMousedown,
            "t-on-mouseup": this.onMouseup,
            "t-on-keydown": this.onKeydown,
        },
        "button.extra_link": {
            "t-on-click.prevent": this.onExtraLinkClick,
        },
        ".s_searchbar_fuzzy_submit": {
            "t-on-click.prevent": (event) => {
                this.inputEl.value = event.target.textContent;
                log.logic("fuzzy submit: searching suggested term");
                const formEl = this.searchBarEl
                    .querySelector(".o_search_order_by")
                    .closest("form");
                formEl.submit();
            },
        },
    };
    autocompleteMinWidth = 300;

    setup() {
        this.searchBarEl = this.el.closest(".o_searchbar_form");
        this.inputEl = this.searchBarEl.querySelector(".search-query");
        this.scrollingParentEl = null;

        const megaMenuEl = this.searchBarEl.closest(".o_mega_menu");
        if (megaMenuEl) {
            const navbarEl = this.searchBarEl.closest(".navbar");
            const navbarTogglerEl = navbarEl
                ? navbarEl.querySelector(".navbar-toggler")
                : null;
            if (navbarTogglerEl && navbarTogglerEl.clientWidth < 1) {
                this.scrollingParentEl = megaMenuEl;
            }
        }

        this.isDropup = false;
        if (
            this.el.getBoundingClientRect().bottom >
            document.documentElement.offsetHeight
        ) {
            this.el.style.overflowY = "auto";
            if (
                this.el.getBoundingClientRect().bottom >
                document.documentElement.offsetHeight
            ) {
                const searchPosition = this.searchBarEl.getBoundingClientRect();
                this.isDropup =
                    searchPosition.top >
                    document.documentElement.offsetHeight - searchPosition.bottom;
            }
        }
        log.lifecycle("setup", () => ({
            inMegaMenu: !!megaMenuEl,
            scrollingParent: !!this.scrollingParentEl,
            isDropup: this.isDropup,
            items: this.el.children.length,
        }));
    }

    onMousedown() {
        if (isBrowserSafari) {
            this.searchBarEl.dispatchEvent(
                new CustomEvent("safarihack", { detail: { linkHasFocus: true } }),
            );
        }
    }

    onMouseup() {
        if (isBrowserSafari) {
            this.searchBarEl.dispatchEvent(
                new CustomEvent("safarihack", { detail: { linkHasFocus: false } }),
            );
        }
    }

    /**
     * @param {MouseEvent} ev
     */
    onKeydown(ev) {
        switch (ev.key) {
            case "ArrowUp":
            case "ArrowDown": {
                ev.preventDefault();
                const focusableEls = [this.inputEl, ...this.el.children];
                const focusedEl = document.activeElement;
                const currentIndex = focusableEls.indexOf(focusedEl) || 0;
                const delta = ev.key === "ArrowUp" ? focusableEls.length - 1 : 1;
                const nextIndex = (currentIndex + delta) % focusableEls.length;
                const nextFocusedEl = focusableEls[nextIndex];
                nextFocusedEl.focus();
                break;
            }
        }
    }

    /**
     * @param {PointerEvent} ev
     */
    onExtraLinkClick(ev) {
        log.logic("onExtraLinkClick: navigating", () => ({
            target: ev.currentTarget.dataset.target,
        }));
        browser.location.href = verifyHttpsUrl(ev.currentTarget.dataset.target);
    }
}

registry
    .category("public.interactions")
    .add("website.search_bar_results", SearchBarResults);
