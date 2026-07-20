/** @odoo-module native */
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";
import { Popover } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

export class CoursePrerequisite extends Interaction {
    static selector = ".o_wslides_js_prerequisite_course";

    start() {
        const bsPopover = Popover.getOrCreateInstance(this.el, {
            trigger: "focus",
            placement: "bottom",
            container: "body",
            html: true,
            content: renderToElement("slide.course.prerequisite", {
                channels: JSON.parse(this.el.dataset.channels),
            }),
        });
        this.registerCleanup(() => bsPopover.dispose());
    }
}

registry
    .category("public.interactions")
    .add("website_slides.course_prerequisite", CoursePrerequisite);
