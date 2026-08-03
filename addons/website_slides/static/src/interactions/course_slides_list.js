/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { CoursePage } from "@website_slides/interactions/course_page";

export class CourseSlidesList extends CoursePage {
    static selector = ".o_wslides_slides_list";

    start() {
        this.channelId = this.el.dataset.channelId;
        this.updateHref();
        this.bindSortable();
    }

    /**
     * Bind the sortable service to both
     * - course sections
     * - course slides
     */
    bindSortable() {
        const sortableBaseParam = {
            clone: false,
            placeholderClasses: [
                "o_wslides_slides_list_slide_hilight",
                "position-relative",
                "mb-1",
            ],
            onDrop: this.reorderSlides.bind(this),
            applyChangeOnDrop: true,
        };

        const containerEl = this.el.querySelector(
            "ul.o_wslides_js_slides_list_container",
        );
        const categorySortable = this.services.sortable
            .create({
                ...sortableBaseParam,
                ref: { el: containerEl },
                elements: ".o_wslides_slide_list_category",
                handle: ".o_wslides_slide_list_category_header .o_wslides_slides_list_drag",
                sortableId: "category",
            })
            .enable();
        this.registerCleanup(() => categorySortable.cleanup());

        const slideSortable = this.services.sortable
            .create({
                ...sortableBaseParam,
                ref: { el: containerEl },
                elements:
                    ".o_wslides_slides_list_slide:not(.o_wslides_js_slides_list_empty):not(.o_not_editable)",
                handle: ".o_wslides_slides_list_drag",
                connectGroups: true,
                groups: ".o_wslides_js_slides_list_container ul",
                sortableId: "list",
            })
            .enable();
        this.registerCleanup(() => slideSortable.cleanup());
    }

    /**
     * This method will check that a section is empty/not empty when the slides
     * are reordered and show/hide the "Empty category" placeholder.
     */
    checkForEmptySections() {
        for (const categoryEl of this.el.querySelectorAll(
            ".o_wslides_slide_list_category",
        )) {
            const headerEl = categoryEl.querySelector(
                ".o_wslides_slide_list_category_header",
            );
            const slideCount = categoryEl.querySelectorAll(
                ".o_wslides_slides_list_slide:not(.o_not_editable)",
            ).length;
            const flagContainerEl = headerEl.querySelector(
                ".o_wslides_slides_list_drag",
            );
            const emptyFlagEl = flagContainerEl?.querySelector("small");
            if (slideCount === 0 && !emptyFlagEl) {
                const smallEl = document.createElement("small");
                smallEl.className = "ms-1 text-muted fw-bold";
                smallEl.textContent = _t("(empty)");
                flagContainerEl.appendChild(smallEl);
            } else if (slideCount > 0 && emptyFlagEl) {
                emptyFlagEl.remove();
            }
        }
    }

    /**
     * Collects all slide IDs in their current DOM order.
     *
     * @returns {number[]}
     */
    getSlides() {
        const slideIds = [];
        for (const el of this.el.querySelectorAll(".o_wslides_js_list_item")) {
            slideIds.push(parseInt(el.dataset.slideId));
        }
        return slideIds;
    }

    async reorderSlides() {
        await this.waitFor(
            this.services.orm.webResequence("slide.slide", this.getSlides()),
        );
        this.checkForEmptySections();
    }

    /**
     * Change links href to fullscreen mode for SEO.
     *
     * Specifications demand that links are generated (xml) without the
     * "fullscreen" parameter for SEO purposes. This method then adds the
     * parameter as soon as the page is loaded.
     */
    updateHref() {
        for (const linkEl of this.el.querySelectorAll(
            ".o_wslides_js_slides_list_slide_link",
        )) {
            const href = linkEl.getAttribute("href");
            const operator = href.indexOf("?") !== -1 ? "&" : "?";
            linkEl.setAttribute("href", href + operator + "fullscreen=1");
        }
    }
}

registry
    .category("public.interactions")
    .add("website_slides.course_slides_list", CourseSlidesList);
