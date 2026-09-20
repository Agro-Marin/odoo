/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { SNIPPET_SPECIFIC_END } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.plugin.carousel_slides_option");

export class CarouselSlidesOption extends BaseOptionComponent {
    static template = "website.CarouselSlidesOption";
    static selector = ".carousel .carousel-item";
    static exclude = ".s_image_gallery .carousel-item";
}

export class CarouselSlidesOptionPlugin extends Plugin {
    static id = "carouselSlidesOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(SNIPPET_SPECIFIC_END, CarouselSlidesOption)],
        builder_actions: {
            MakeSlideClickableAction,
            SetSlideAnchorUrlAction,
        },
        clean_for_save_handlers: this.cleanForSave.bind(this),
        legit_empty_link_predicates: (linkEl) =>
            linkEl.matches(".carousel-item a.slide-link"),
    };

    /**
     * @param {HTMLElement} root
     */
    cleanForSave({ root }) {
        const noLinkSlideEls = root.querySelectorAll(
            ".carousel-item.clickable-slide:not(:has(.slide-link))",
        );
        log.pipeline("CarouselSlidesOptionPlugin cleanForSave", () => ({
            unlinkedClickableSlides: noLinkSlideEls.length,
        }));
        for (const slideEl of noLinkSlideEls) {
            slideEl.classList.remove("clickable-slide");
        }
    }
}

class MakeSlideClickableAction extends BuilderAction {
    static id = "makeSlideClickable";
    setup() {
        this.preview = false;
    }
    clean({ editingElement }) {
        const linkEl = editingElement.querySelector("a.slide-link");
        log.logic("MakeSlideClickableAction clean", () => ({ hadLink: !!linkEl }));
        linkEl?.remove();
    }
}

class SetSlideAnchorUrlAction extends BuilderAction {
    static id = "setSlideAnchorUrl";
    setup() {
        this.preview = false;
    }
    apply({ editingElement, value }) {
        const url = value;
        const linkEl = editingElement.querySelector("a.slide-link");

        if (!url) {
            log.logic("SetSlideAnchorUrlAction apply: remove link", () => ({
                hadLink: !!linkEl,
            }));
            linkEl.remove();
            return;
        }
        if (linkEl) {
            log.logic("SetSlideAnchorUrlAction apply: update href", () => ({ url }));
            linkEl.setAttribute("href", url);
            return;
        }
        log.logic("SetSlideAnchorUrlAction apply: create link", () => ({ url }));
        const anchorEl = document.createElement("a");
        anchorEl.className =
            "slide-link position-absolute top-0 start-0 w-100 h-100 d-none";
        anchorEl.setAttribute("href", url);
        anchorEl.style.zIndex = 100;
        editingElement.prepend(anchorEl);
    }
    getValue({ editingElement }) {
        const linkEl = editingElement.querySelector("a.slide-link");
        return linkEl?.getAttribute("href") || "";
    }
}

registry
    .category("website-plugins")
    .add(CarouselSlidesOptionPlugin.id, CarouselSlidesOptionPlugin);
