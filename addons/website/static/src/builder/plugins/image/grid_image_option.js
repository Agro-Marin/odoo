/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.grid_image_option");

export class GridImageOption extends BaseOptionComponent {
    static template = "website.GridImageOption";
    static selector = "img";

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => ({
            isOptionActive: this.isOptionActive(editingElement),
        }));
    }

    isOptionActive(editingElement) {
        const imageGridItemEl = editingElement.closest(".o_grid_item_image");
        const hasSquareShape =
            editingElement.dataset.shape === "html_builder/geometric/geo_square";
        const effectAllowsOption = ![
            "dolly_zoom",
            "outline",
            "image_mirror_blur",
        ].includes(editingElement.dataset.hoverEffect);

        return (
            !!imageGridItemEl &&
            (!("shape" in editingElement.dataset) ||
                (hasSquareShape && effectAllowsOption))
        );
    }
}
