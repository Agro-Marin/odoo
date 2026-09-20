/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.snippet.s_announcement_scroll");

export class AnnouncementScroll extends Interaction {
    static selector = ".s_announcement_scroll";

    dynamicContent = {
        _root: {
            "t-att-class": () => ({
                s_announcement_scroll_ready: this.announcementScrollReady,
                s_announcement_scroll_page_scrolling:
                    this.announcementScrollPageScrolling,
            }),
        },
        _window: {
            "t-on-resize": this.debounced(this.onResize, 100, {
                leading: true,
                trailing: true,
            }),
            "t-on-scroll": this.throttled(this.onScroll),
        },
        ".s_announcement_scroll_marquee_container": {
            "t-att-style": () => ({
                transform: `translateX(${this.parallaxPosition}%)`,
            }),
        },
    };

    setup() {
        this.marqueeContainerEl = this.el.querySelector(
            ".s_announcement_scroll_marquee_container",
        );
        this.marqueeItemEl = this.el.querySelector(
            ".s_announcement_scroll_marquee_item",
        );
        this.setParallaxPosition();
    }

    start() {
        log.lifecycle("start", () => ({
            parallax: this.el.classList.contains("s_announcement_scroll_parallax"),
        }));
        this.updateMarqueeLayout();
        this.announcementScrollReady = true;
        this.updateContent();
    }

    destroy() {
        log.lifecycle("destroy: undo marquee layout");
        this.undoMarqueeLayout();
    }

    onResize() {
        this.announcementScrollReady = false;
        this.updateContent();

        this.updateMarqueeLayout();
        this.announcementScrollReady = true;
    }

    onScroll() {
        this.announcementScrollPageScrolling = true;
        window.clearTimeout(this.scrollingTimeout);
        this.scrollingTimeout = this.waitForTimeout(() => {
            this.announcementScrollPageScrolling = false;
        }, 200);

        this.setParallaxPosition();
    }

    setParallaxPosition() {
        const MIN_LEFT_SHIFT = 50;

        if (
            !this.el.classList.contains("s_announcement_scroll_parallax") ||
            window.matchMedia("(prefers-reduced-motion: reduce)").matches === true
        ) {
            this.parallaxPosition = -MIN_LEFT_SHIFT;
            return;
        }

        const PARALLAX_AMOUNT = 50;
        const rect = this.el.getBoundingClientRect();
        const startScroll = window.scrollY + rect.top - window.innerHeight;
        const endScroll = window.scrollY + rect.bottom;
        const progress = Math.min(
            Math.max((window.scrollY - startScroll) / (endScroll - startScroll), 0),
            1,
        );
        if (this.el.classList.contains("s_announcement_scroll_direction_right")) {
            this.parallaxPosition =
                -MIN_LEFT_SHIFT - PARALLAX_AMOUNT + progress * PARALLAX_AMOUNT;
        } else {
            this.parallaxPosition = -MIN_LEFT_SHIFT - progress * PARALLAX_AMOUNT;
        }
    }

    undoMarqueeLayout() {
        while (this.marqueeContainerEl.children.length > 1) {
            this.marqueeContainerEl.lastChild.remove();
        }
        this.marqueeContainerEl.style.removeProperty("--marquee-item-size");
    }

    updateMarqueeLayout() {
        const marqueeItemElWidth = this.marqueeItemEl.offsetWidth;
        const itemsPerContainer = Math.ceil(
            this.marqueeContainerEl.offsetWidth / marqueeItemElWidth,
        );
        if (itemsPerContainer > 100) {
            log.logic(
                "updateMarqueeLayout: too many items per container, skipped",
                () => ({
                    itemsPerContainer,
                    itemWidth: marqueeItemElWidth,
                }),
            );
            return;
        }

        this.undoMarqueeLayout();

        this.marqueeContainerEl.style.setProperty(
            "--marquee-item-size",
            marqueeItemElWidth,
        );

        const cloneCount = itemsPerContainer * 2 + 1;
        log.pipeline("updateMarqueeLayout: cloning items", () => ({
            itemsPerContainer,
            cloneCount,
        }));
        for (let i = 0; i < cloneCount; i++) {
            const cloneEl = this.marqueeItemEl.cloneNode(true);
            cloneEl.classList.add("s_announcement_scroll_marquee_item_clone");
            cloneEl.prepend(document.createTextNode("\u00A0"));
            this.marqueeContainerEl.appendChild(cloneEl);
        }
    }
}

registry
    .category("public.interactions")
    .add("website.announcement_scroll", AnnouncementScroll);
