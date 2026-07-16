/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";

import { CardImageAlignmentOption } from "./card_image_alignment_option.js";

export class CardImageOption extends BaseOptionComponent {
    static template = "website.CardImageOption";
    static components = { CardImageAlignmentOption };

    setup() {
        super.setup();
        this.state = useDomState((editingElement) => ({
            hasCoverImage: !!editingElement.querySelector(
                ":scope > .o_card_img_wrapper",
            ),
        }));
    }
}
