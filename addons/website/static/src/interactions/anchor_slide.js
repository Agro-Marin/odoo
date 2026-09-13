/** @odoo-module native */
import { scrollTo } from "@html_builder/utils/scrolling";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Collapse, Offcanvas } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.anchor_slide");

export class AnchorSlide extends Interaction {
    static selector = "a[href^='/'][href*='#'], a[href^='#']";
    dynamicContent = {
        _root: {
            "t-on-click": this.animateClick,
        },
    };

    setup() {
        const hash = window.location.hash.substring(1);
        const anchorEl = document.getElementById(hash);
        if (anchorEl && anchorEl.classList.contains("accordion-item")) {
            log.logic("AnchorSlide setup: open accordion from location hash", () => ({
                hash,
            }));
            this.handleAccordionAnchor(anchorEl);
        }
    }

    /**
     * @param {HTMLElement} el
     * @param {string} [scrollValue='true']
     * @returns {Promise}
     */
    scrollTo(el, scrollValue = "true") {
        return scrollTo(el, {
            duration: scrollValue === "true" ? 500 : 0,
            extraOffset: this.computeExtraOffset(),
        });
    }

    computeExtraOffset() {
        return 0;
    }

    /**
     * @param {HTMLElement} anchorEl
     */
    handleAccordionAnchor(anchorEl) {
        const accordionCollapseEl = anchorEl.querySelector(".accordion-collapse");
        Collapse.getOrCreateInstance(accordionCollapseEl, {
            toggle: false,
        }).show();
    }

    /**
     * @param {MouseEvent} ev
     */
    animateClick(ev) {
        const ensureSlash = (path) => (path.endsWith("/") ? path : path + "/");
        if (ensureSlash(this.el.pathname) !== ensureSlash(window.location.pathname)) {
            log.logic(
                "AnchorSlide animateClick: other page, native navigation",
                () => ({
                    href: this.el.pathname,
                    current: window.location.pathname,
                }),
            );
            return;
        }
        if (this.el.pathname !== window.location.pathname) {
            this.el.pathname = window.location.pathname;
        }
        let hash = this.el.hash;
        if (!hash.length) {
            log.logic("AnchorSlide animateClick: empty hash", () => ({
                href: this.el.getAttribute("href"),
            }));
            return;
        }
        hash = "#" + CSS.escape(hash.substring(1));
        const anchorEl = this.el.ownerDocument.querySelector(hash);
        const scrollValue = anchorEl?.dataset.anchor;
        if (!anchorEl || !scrollValue || this.el.target === "_blank") {
            log.logic("AnchorSlide animateClick: no animated scroll", () => ({
                hash,
                hasAnchor: !!anchorEl,
                scrollValue,
                target: this.el.target,
            }));
            return;
        }

        if (anchorEl.classList.contains("accordion-item")) {
            this.handleAccordionAnchor(anchorEl);
        }
        const offcanvasEl = this.el.closest(".offcanvas.o_navbar_mobile");
        log.pipeline("AnchorSlide animateClick: scroll", () => ({
            hash,
            scrollValue,
            accordion: anchorEl.classList.contains("accordion-item"),
            afterOffcanvasHide: !!offcanvasEl?.classList.contains("show"),
        }));
        if (offcanvasEl && offcanvasEl.classList.contains("show")) {
            ev.preventDefault();
            Offcanvas.getInstance(offcanvasEl).hide();
            this.addListener(
                offcanvasEl,
                "hidden.bs.offcanvas",
                () => this.manageScroll(hash, anchorEl, scrollValue),
                { once: true },
            );
        } else {
            ev.preventDefault();
            this.manageScroll(hash, anchorEl, scrollValue);
        }
    }

    /**
     * @param {string} hash
     * @param {HTMLElement} anchorEl
     * @param {string} [scrollValue='true']
     */
    manageScroll(hash, anchorEl, scrollValue = "true") {
        if (hash === "#top" || hash === "#bottom") {
            this.scrollTo(hash);
        } else {
            this.scrollTo(anchorEl, scrollValue);
        }
    }
}

registry.category("public.interactions").add("website.anchor_slide", AnchorSlide);
