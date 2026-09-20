/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { CardImageAlignmentOption } from "./card_image_alignment_option.js";

const log = makeLogger("website.builder.option.card_image_option");

export class CardImageOption extends BaseOptionComponent {
    static template = "website.CardImageOption";
    static components = { CardImageAlignmentOption };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => ({
            hasCoverImage: !!editingElement.querySelector(
                ":scope > .o_card_img_wrapper",
            ),
        }));
    }
}
