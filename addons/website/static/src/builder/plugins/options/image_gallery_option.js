/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { BorderConfigurator } from "@html_builder/plugins/border_configurator_option";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.image_gallery_option");

export class ImageGalleryComponent extends BaseOptionComponent {
    static template = "website.ImageGalleryOption";
    static selector = ".s_image_gallery";

    static components = { BorderConfigurator };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => ({
            isSlideShow: editingElement.classList.contains("o_slideshow"),
        }));
    }
}
