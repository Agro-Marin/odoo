/** @odoo-module native */
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { registry } from "@web/core/registry";
import { Carousel } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";
import { onceAllImagesLoaded } from "@website/utils/images";

export class CarouselSlider extends Interaction {
    static selector = ".carousel";
    dynamicContent = {
        _root: {
            "t-on-slide.bs.carousel": this.onSlideCarousel,
            "t-on-slid.bs.carousel": this.onSlidCarousel,
        },
        img: {
            "t-on-load": this.computeMaxHeight,
        },
        _window: {
            "t-on-resize": this.debounced(this.computeMaxHeight, 250),
        },
        ".carousel-item": {
            "t-att-style": () => ({
                "min-height": this.maxHeight ? `${this.maxHeight}px` : "",
            }),
        },
        ".slide-link": {
            "t-att-class": () => ({ "d-none": !this.showClickableSlideLinks }),
        },
        ".carousel-indicators button, .carousel-indicators li": {
            "t-on-pointerdown": (ev) => {
                const toLoadEl = this.carouselItemEls.at(
                    ev.currentTarget.dataset.bsSlideTo,
                );
                this.prefetchImages([toLoadEl]);
            },
            "t-on-keydown": (ev) => {
                const hotkey = getActiveHotkey(ev);
                if (["space", "enter"].includes(hotkey)) {
                    const toLoadEl = this.carouselItemEls.at(
                        ev.currentTarget.dataset.bsSlideTo,
                    );
                    this.prefetchImages([toLoadEl]);
                }
            },
        },
    };
    carouselOptions = undefined;
    showClickableSlideLinks = true;

    setup() {
        this.maxHeight = undefined;
        this.carouselInnerEl = this.el.querySelector(".carousel-inner");
        if (this.carouselInnerEl) {
            this.carouselItemEls = [
                ...this.carouselInnerEl.querySelectorAll(".carousel-item"),
            ];
        }

        const itemWidth = getComputedStyle(this.el).getPropertyValue(
            "--o-carousel-item-width-percentage",
        );
        this.options = {
            scrollMode: this.el.classList.contains("o_carousel_multi_items")
                ? "single"
                : "all",
            itemsPerSlide: itemWidth ? Math.round(100 / parseFloat(itemWidth)) : 1,
        };

        this.hasInterval = ![undefined, "false", "0"].includes(
            this.el.dataset.bsInterval,
        );
        if (!["true", "carousel", "false"].includes(this.el.dataset.bsRide)) {
            this.el.dataset.bsRide = this.hasInterval ? "carousel" : "false";
        }
        if (this.el.dataset.bsRide === "false") {
            Carousel.getOrCreateInstance(this.el, { ride: false, pause: true });
        } else if (!this.hasInterval) {
            this.el.dataset.bsInterval = "1000";
        }
    }

    start() {
        this.computeMaxHeight();
        this.updateContent();
        const carouselBS = Carousel.getOrCreateInstance(this.el, this.carouselOptions);
        this.registerCleanup(() => carouselBS.dispose());

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    this.loadItemsToAppear();
                    observer.unobserve(this.el);
                }
            });
        });
        observer.observe(this.el);
        this.registerCleanup(() => observer.disconnect());
    }

    computeMaxHeight() {
        this.maxHeight = undefined;
        this.updateContent();
        for (const itemEl of this.el.querySelectorAll(".carousel-item")) {
            const isActive = itemEl.classList.contains("active");
            itemEl.classList.add("active");
            const height = itemEl.offsetHeight;
            if (height > this.maxHeight || this.maxHeight === undefined) {
                this.maxHeight = height;
            }
            itemEl.classList.toggle("active", isActive);
        }
    }

    /**
     * @param {Event} ev
     */
    onSlideCarousel(ev) {
        if (!this.carouselInnerEl) {
            return;
        }
        const imageEls = [...this.carouselInnerEl.querySelectorAll("img")];
        const isLoading = imageEls.some((el) => el.loading !== "lazy" && !el.complete);
        if (isLoading) {
            ev.preventDefault();
            onceAllImagesLoaded(this.carouselInnerEl).then(() => {
                Carousel.getOrCreateInstance(this.el).to(ev.to);
            });
            return;
        }
        if (this.options.scrollMode === "single") {
            this.onSlideSingleScroll(ev);
        }
    }

    /**
     * @param {Event} ev
     */
    onSlidCarousel(ev) {
        if (this.options.scrollMode === "single") {
            this.onSlidSingleScroll(ev);
        }
        this.loadItemsToAppear();
    }

    /**
     * @param {Event} ev
     */
    onSlideSingleScroll(ev) {
        if (ev.direction === "right") {
            const carouselItemsEls = Array.from(
                this.carouselInnerEl.querySelectorAll(".carousel-item"),
            );
            this.carouselInnerEl.prepend(carouselItemsEls.pop());
        }
    }

    /**
     * @param {Event} ev
     */
    onSlidSingleScroll(ev) {
        if (ev.direction === "left") {
            const carouselItemsEls =
                this.carouselInnerEl.querySelectorAll(".carousel-item");
            this.carouselInnerEl.appendChild(carouselItemsEls[0]);
        }
    }

    /**
     * @param {number} [nbItemsToLoad=1]
     */
    loadItemsToAppear(nbItemsToLoad = 1) {
        if (!this.carouselInnerEl) {
            return;
        }
        const index = this.carouselItemEls.findIndex((el) =>
            el.classList.contains("active"),
        );
        const activeItemIndex = index >= 0 ? index : 0;

        const nbItemElsOnScreen =
            this.options.scrollMode === "single" ? this.options.itemsPerSlide + 1 : 1;
        const nextEndIndex = Math.min(
            activeItemIndex + nbItemElsOnScreen + nbItemsToLoad + 1,
            this.carouselItemEls.length,
        );
        const nextItemElsToLoad = this.carouselItemEls.slice(
            activeItemIndex,
            nextEndIndex,
        );

        let prevItemElsToLoad;
        if (activeItemIndex - nbItemsToLoad < 0) {
            const wrapAmount = Math.abs(activeItemIndex - nbItemsToLoad);
            prevItemElsToLoad = this.carouselItemEls
                .slice(
                    this.carouselItemEls.length - wrapAmount,
                    this.carouselItemEls.length,
                )
                .concat(this.carouselItemEls.slice(0, activeItemIndex))
                .reverse();
        } else {
            prevItemElsToLoad = this.carouselItemEls
                .slice(activeItemIndex - nbItemsToLoad, activeItemIndex)
                .reverse();
        }

        this.prefetchImages(nextItemElsToLoad.concat(prevItemElsToLoad));
    }

    /**
     * @param {HTMLElement[]} toLoadEls
     */
    prefetchImages(toLoadEls) {
        for (const carouselItemEl of toLoadEls) {
            const imageEls = carouselItemEl.querySelectorAll("img[loading='lazy']");
            for (const imageEl of imageEls) {
                imageEl.removeAttribute("loading");
            }
        }
    }
}

registry.category("public.interactions").add("website.carousel_slider", CarouselSlider);
