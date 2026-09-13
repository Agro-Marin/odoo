/** @odoo-module native */
import { getBootstrapComponent } from "@html_builder/core/bootstrap_realm";
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { between } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";
import { renderToElement } from "@web/core/utils/render";
import {
    BOX_BORDER_SHADOW,
    WEBSITE_BACKGROUND_OPTIONS,
} from "@website/builder/option_sequence";

import { CarouselItemHeaderMiddleButtons } from "./carousel_item_header_buttons.js";

const log = makeLogger("website.builder.plugin.carousel_option");

/**
 * @typedef { Object } CarouselOptionShared
 * @property { CarouselOptionPlugin['addSlide'] } addSlide
 * @property { CarouselOptionPlugin['removeSlide'] } removeSlide
 * @property { CarouselOptionPlugin['slideCarousel'] } slideCarousel
 */

export const CAROUSEL_CARDS_SEQUENCE = between(
    WEBSITE_BACKGROUND_OPTIONS,
    BOX_BORDER_SHADOW,
);

const carouselWrapperSelector =
    ".s_carousel_wrapper, .s_carousel_intro_wrapper, .s_carousel_cards_wrapper, .s_quotes_carousel_wrapper";
const carouselControlsSelector =
    ".carousel-control-prev, .carousel-control-next, .carousel-indicators";

const carouselItemOptionSelector =
    ".s_carousel .carousel-item, .s_quotes_carousel .carousel-item, .s_carousel_intro .carousel-item, .s_carousel_cards .carousel-item";

export class CarouselOption extends BaseOptionComponent {
    static template = "website.CarouselOption";
    static selector = "section";
    static exclude =
        ".s_carousel_intro_wrapper, .s_carousel_cards_wrapper, .s_quotes_carousel_wrapper:has(>.s_quotes_carousel_compact)";
    static applyTo = ":scope > .carousel";
}

export class CarouselBottomControllersOption extends BaseOptionComponent {
    static template = "website.CarouselBottomControllersOption";
    static selector = "section";
    static applyTo = ".s_carousel_intro, .s_quotes_carousel_compact";
}

export class CarouselCardsOption extends BaseOptionComponent {
    static template = "website.CarouselCardsOption";
    static selector = "section";
    static applyTo = ".s_carousel_cards";
}

export class CarouselOptionPlugin extends Plugin {
    static id = "carouselOption";
    static dependencies = ["clone", "builderOptions", "builderActions"];
    static shared = ["addSlide", "removeSlide", "slideCarousel"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            CarouselOption,
            CarouselBottomControllersOption,
            withSequence(CAROUSEL_CARDS_SEQUENCE, CarouselCardsOption),
        ],
        builder_header_middle_buttons: {
            Component: CarouselItemHeaderMiddleButtons,
            selector: carouselItemOptionSelector,
            props: {
                addSlide: (editingElement) => this.addSlide(editingElement),
                removeSlide: async (editingElement) => {
                    if (editingElement.parentElement) {
                        await this.removeSlide(editingElement.closest(".carousel"));
                    }
                },
                applyAction: this.dependencies.builderActions.applyAction,
            },
        },
        container_title: {
            selector: carouselItemOptionSelector,
            getTitleExtraInfo: (editingElement) =>
                this.getTitleExtraInfo(editingElement),
        },
        builder_actions: {
            AddSlideAction,
            SlideCarouselAction,
            ToggleControllersAction,
            ToggleCardImgAction,
        },
        on_cloned_handlers: this.onCloned.bind(this),
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
        get_gallery_items_handlers: this.getGalleryItems.bind(this),
        reorder_items_handlers: this.reorderCarouselItems.bind(this),
        before_save_handlers: this.restoreCarousels.bind(this),
        is_unremovable_selector: carouselItemOptionSelector,
    };

    restoreCarousels(rootEl = this.editable) {
        const endRestore = log.perf("restoreCarousels");
        for (const carouselEl of selectElements(rootEl, ".carousel")) {
            carouselEl.querySelectorAll(".carousel-item").forEach((itemEl, i) => {
                itemEl.classList.remove("next", "prev", "left", "right");
                itemEl.classList.toggle("active", i === 0);
            });
            carouselEl
                .querySelectorAll(".carousel-indicators > *")
                .forEach((indicatorEl, i) => {
                    indicatorEl.classList.toggle("active", i === 0);
                    indicatorEl.removeAttribute("aria-current");
                    if (i === 0) {
                        indicatorEl.setAttribute("aria-current", "true");
                    }
                });
        }
        endRestore();
    }

    getTitleExtraInfo(editingElement) {
        const itemEls = [...editingElement.parentElement.children];
        const activeIndex = itemEls.indexOf(editingElement);
        const updatedText = ` (${activeIndex + 1}/${itemEls.length})`;
        return updatedText;
    }

    /**
     * @param {HTMLElement} editingElement
     */
    async addSlide(editingElement) {
        const activeItemEl = editingElement.querySelector(".carousel-item.active");
        const endClone = log.perf("addSlide clone active item", () => ({
            carouselId: editingElement.id,
        }));
        const newItemEl = await this.dependencies.clone.cloneElement(activeItemEl, {
            activateClone: false,
        });
        endClone();
        newItemEl.classList.remove("active");

        const controlEls = editingElement.querySelectorAll(carouselControlsSelector);
        controlEls.forEach((controlEl) => {
            controlEl.classList.remove("d-none");
        });

        const indicatorsEl = editingElement.querySelector(".carousel-indicators");
        const newIndicatorEl = this.document.createElement("button");
        newIndicatorEl.setAttribute("data-bs-target", "#" + editingElement.id);
        newIndicatorEl.setAttribute("aria-label", _t("Carousel indicator"));
        indicatorsEl.appendChild(newIndicatorEl);

        log.pipeline("addSlide slide to new item", () => ({
            controls: controlEls.length,
            indicators: indicatorsEl.children.length,
        }));
        const endSlide = log.perf("addSlide slide next");
        await this.slide(editingElement, "next");
        endSlide();
    }

    /**
     * @param {HTMLElement} editingElement
     */
    async removeSlide(editingElement) {
        const itemEls = [...editingElement.querySelectorAll(".carousel-item")];
        const newLength = itemEls.length - 1;
        log.logic("removeSlide", () => ({ carouselId: editingElement.id, newLength }));
        if (newLength > 0) {
            const activeItemEl = editingElement.querySelector(".carousel-item.active");
            const activeIndicatorEl = editingElement.querySelector(
                ".carousel-indicators > .active",
            );
            const endSlide = log.perf("removeSlide slide prev");
            await this.slide(editingElement, "prev");
            endSlide();

            activeItemEl.remove();
            activeIndicatorEl.remove();

            const controlEls = editingElement.querySelectorAll(
                carouselControlsSelector,
            );
            controlEls.forEach((controlEl) =>
                controlEl.classList.toggle("d-none", newLength === 1),
            );
        }
    }

    /**
     * @param {HTMLElement} editingElement
     * @param {String} direction
     */
    async slideCarousel(editingElement, direction) {
        log.pipeline("slideCarousel", { direction });
        await this.slide(editingElement, direction);
    }

    /**
     * @param {String|Number} direction
     * @param {Element} editingElement
     * @returns {Promise}
     */
    slide(editingElement, direction) {
        const endSlideTransition = log.perf("slide", () => ({
            carouselId: editingElement.id,
            direction,
        }));
        editingElement.addEventListener(
            "slide.bs.carousel",
            () => {
                this.slideTimestamp = window.performance.now();
            },
            { once: true },
        );

        return new Promise((resolve) => {
            let settled = false;
            const finalize = () => {
                if (settled) {
                    log.logic("slide finalize skip: already settled");
                    return;
                }
                settled = true;
                endSlideTransition();
                const itemEls = editingElement.querySelectorAll(".carousel-item");
                const activeItemEl = editingElement.querySelector(
                    ".carousel-item.active",
                );
                const activeIndex = [...itemEls].indexOf(activeItemEl);
                updateCarouselIndicators(editingElement, activeIndex);

                this.dependencies["builderOptions"].setNextTarget(activeItemEl);

                resolve();
            };
            editingElement.addEventListener(
                "slid.bs.carousel",
                () => {
                    const slideDuration =
                        window.performance.now() - this.slideTimestamp;
                    setTimeout(finalize, 0.2 * slideDuration);
                },
                { once: true },
            );
            setTimeout(finalize, 3000);

            const win = editingElement.ownerDocument.defaultView;
            const Carousel = getBootstrapComponent(win, "Carousel");
            if (!Carousel) {
                log.logic(
                    "slide fallback: no bootstrap Carousel, moving item directly",
                );
                // a page that publishes no edit bundle still gets the move,
                // without the transition
                this.moveActiveItem(editingElement, direction);
                finalize();
                return;
            }
            const carouselInstance = Carousel.getOrCreateInstance(editingElement, {
                ride: false,
                pause: true,
                keyboard: false,
            });
            if (typeof direction === "number") {
                carouselInstance.to(direction);
            } else {
                carouselInstance[direction]();
            }
        });
    }

    /**
     * @param {Element} editingElement
     * @param {String|Number} direction
     */
    moveActiveItem(editingElement, direction) {
        const itemEls = [...editingElement.querySelectorAll(".carousel-item")];
        if (!itemEls.length) {
            log.logic("moveActiveItem skip: no carousel items");
            return;
        }
        const activeIndex = itemEls.findIndex((el) => el.classList.contains("active"));
        let index;
        if (typeof direction === "number") {
            index = direction;
        } else if (direction === "prev") {
            index = activeIndex - 1;
        } else {
            index = activeIndex + 1;
        }
        index = ((index % itemEls.length) + itemEls.length) % itemEls.length;
        log.pipeline("moveActiveItem", { direction, activeIndex, index });
        itemEls.forEach((el, i) => el.classList.toggle("active", i === index));
    }

    onCloned({ cloneEl }) {
        if (cloneEl.matches(carouselWrapperSelector)) {
            log.pipeline("onCloned assign unique carousel id");
            this.assignUniqueID(cloneEl);
        }
    }

    onSnippetDropped({ snippetEl }) {
        if (snippetEl.matches(carouselWrapperSelector)) {
            log.pipeline("onSnippetDropped assign unique carousel id", () => ({
                snippet: snippetEl.dataset.snippet,
            }));
            this.assignUniqueID(snippetEl);
        }
    }

    /**
     * @param {HTMLElement} editingElement
     */
    assignUniqueID(editingElement) {
        const id = uniqueId("myCarousel");
        log.pipeline("assignUniqueID", () => ({
            id,
            targets: editingElement.querySelectorAll(
                "[data-bs-target], [data-bs-slide], [data-bs-slide-to]",
            ).length,
        }));
        editingElement.querySelector(".carousel").setAttribute("id", id);
        editingElement.querySelectorAll("[data-bs-target]").forEach((el) => {
            el.setAttribute("data-bs-target", "#" + id);
        });
        editingElement
            .querySelectorAll("[data-bs-slide], [data-bs-slide-to]")
            .forEach((el) => {
                if (el.hasAttribute("data-bs-target")) {
                    el.setAttribute("data-bs-target", "#" + id);
                } else if (el.hasAttribute("href")) {
                    el.setAttribute("href", "#" + id);
                }
            });
    }

    /**
     * @param {HTMLElement} activeItemEl
     * @param {String} optionName
     * @returns {Array<HTMLElement>}
     */
    getGalleryItems(activeItemEl, optionName) {
        let itemEls = [];
        if (optionName === "Carousel") {
            const carouselEl = activeItemEl.closest(".carousel");
            itemEls = [...carouselEl.querySelectorAll(".carousel-item")];
            log.pipeline("getGalleryItems", () => ({ count: itemEls.length }));
        }
        return itemEls;
    }

    /**
     * @param {HTMLElement} activeItemEl
     * @param {Array<HTMLElement>} itemEls
     * @param {String} optionName
     */
    reorderCarouselItems(activeItemEl, itemEls, optionName) {
        if (optionName === "Carousel") {
            const carouselEl = activeItemEl.closest(".carousel");

            const carouselInnerEl = carouselEl.querySelector(".carousel-inner");
            const newCarouselInnerEl = document.createElement("div");
            newCarouselInnerEl.classList.add("carousel-inner");
            newCarouselInnerEl.append(...itemEls);
            carouselInnerEl.replaceWith(newCarouselInnerEl);

            const newPosition = itemEls.indexOf(activeItemEl);
            log.pipeline("reorderCarouselItems", () => ({
                count: itemEls.length,
                newPosition,
            }));
            updateCarouselIndicators(carouselEl, newPosition);

            this.dependencies.builderOptions.setNextTarget(activeItemEl);
        }
    }
}

/**
 * @param {HTMLElement} carouselEl
 * @param {Number} newPosition
 */
export function updateCarouselIndicators(carouselEl, newPosition) {
    const indicatorEls = carouselEl.querySelectorAll(".carousel-indicators > *");
    indicatorEls.forEach((indicatorEl, i) => {
        indicatorEl.classList.toggle("active", i === newPosition);
        indicatorEl.removeAttribute("aria-current");
        if (i === newPosition) {
            indicatorEl.setAttribute("aria-current", "true");
        }
    });
}
export class AddSlideAction extends BuilderAction {
    static id = "addSlide";
    static dependencies = ["carouselOption"];
    setup() {
        this.preview = false;
    }
    async apply({ editingElement }) {
        log.pipeline("AddSlideAction apply", () => ({ carouselId: editingElement.id }));
        return this.dependencies.carouselOption.addSlide(editingElement);
    }
}
export class SlideCarouselAction extends BuilderAction {
    static id = "slideCarousel";
    static dependencies = ["carouselOption"];
    setup() {
        this.preview = false;
        this.withLoadingEffect = false;
    }
    async apply({ editingElement, params: { direction } }) {
        log.pipeline("SlideCarouselAction apply", { direction });
        await this.dependencies.carouselOption.slideCarousel(editingElement, direction);
    }
}

export class ToggleControllersAction extends BuilderAction {
    static id = "toggleControllers";
    apply({ editingElement }) {
        const carouselEl = editingElement.closest(".carousel");
        const indicatorsEl = carouselEl.querySelector(".carousel-indicators");
        const areControllersHidden =
            carouselEl.classList.contains("s_carousel_arrows_hidden") &&
            indicatorsEl.classList.contains("s_carousel_indicators_hidden");
        log.logic("ToggleControllersAction apply", { areControllersHidden });
        carouselEl.classList.toggle(
            "s_carousel_controllers_hidden",
            areControllersHidden,
        );
    }
}
export class ToggleCardImgAction extends BuilderAction {
    static id = "toggleCardImg";
    apply({ editingElement }) {
        const carouselEl = editingElement.closest(".carousel");
        const cardEls = carouselEl.querySelectorAll(".card");
        const endRender = log.perf(
            "ToggleCardImgAction apply render image wrappers",
            () => ({
                cards: cardEls.length,
            }),
        );
        for (const cardEl of cardEls) {
            const imageWrapperEl = renderToElement(
                "website.s_carousel_cards.imageWrapper",
            );
            cardEl.insertAdjacentElement("afterbegin", imageWrapperEl);
        }
        endRender();
    }
    clean({ editingElement: el }) {
        const carouselEl = el.closest(".carousel");
        log.pipeline("ToggleCardImgAction clean remove figures", () => ({
            count: carouselEl.querySelectorAll("figure").length,
        }));
        carouselEl.querySelectorAll("figure").forEach((el) => el.remove());
    }
    isApplied({ editingElement }) {
        const carouselEl = editingElement.closest(".carousel");
        const cardImgEl = carouselEl.querySelector(".o_card_img_wrapper");
        return !!cardImgEl;
    }
}

registry.category("website-plugins").add(CarouselOptionPlugin.id, CarouselOptionPlugin);
