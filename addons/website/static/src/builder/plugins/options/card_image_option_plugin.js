/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { ClassAction } from "@html_builder/core/core_builder_action_plugin";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";

const log = makeLogger("website.builder.plugin.card_image_option");

/**
 * @typedef { Object } CardImageOptionShared
 * @property { CardImageOptionPlugin['adaptRatio'] } adaptRatio
 */

const ratiosOnlySupportedForTopBottomImage = [
    "ratio ratio-4x3",
    "ratio ratio-16x9",
    "ratio ratio-21x9",
    "ratio o_card_img_ratio_custom",
];
const imageRelatedClasses = [
    "o_card_img_top",
    "o_card_img_bottom",
    "o_card_img_horizontal",
    "flex-lg-row",
    "flex-lg-row-reverse",
    "flex-column-reverse",
];
const imageRelatedStyles = [
    "--card-img-aspect-ratio",
    "--card-img-size-h",
    "--card-img-ratio-align",
];

class CardImageOptionPlugin extends Plugin {
    static id = "cardImageOption";
    static dependencies = ["remove", "history", "builderOptions"];
    static shared = ["adaptRatio"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            SetCoverImagePositionAction,
            RemoveCoverImageAction,
            AddCoverImageAction,
            AlignCoverImageAction,
        },
    };

    setup() {
        super.setup();
        this.classAction = new ClassAction(this);
        log.lifecycle("CardImageOptionPlugin setup");
    }
    adaptRatio(editingElement, imagePositionClass) {
        if (["card-img-top", "card-img-bottom"].includes(imagePositionClass)) {
            log.logic(
                "adaptRatio skipped: top or bottom image keeps its ratio",
                () => ({
                    imagePositionClass,
                }),
            );
            return;
        }
        const imageWrapper = editingElement.querySelector(".o_card_img_wrapper");
        const asMainParam = (mainParam) => ({
            editingElement: imageWrapper,
            params: { mainParam },
        });
        for (const ratioClasses of ratiosOnlySupportedForTopBottomImage) {
            if (this.classAction.isApplied(asMainParam(ratioClasses))) {
                log.logic("adaptRatio reset unsupported ratio to 1x1", () => ({
                    ratioClasses,
                    imagePositionClass,
                }));
                this.classAction.clean(asMainParam(ratioClasses));
                this.classAction.apply(asMainParam("ratio ratio-1x1"));
                return;
            }
        }
    }
}

export class SetCoverImagePositionAction extends BuilderAction {
    static id = "setCoverImagePosition";
    static dependencies = ["cardImageOption"];
    apply({ editingElement, params: { mainParam: className } }) {
        const imageEl = editingElement.querySelector(".o_card_img");
        log.pipeline("SetCoverImagePositionAction apply", () => ({ className }));
        imageEl.classList.add(className);
        this.dependencies.cardImageOption.adaptRatio(editingElement, className);
    }
    clean({ editingElement, params: { mainParam: className } }) {
        const imageEl = editingElement.querySelector(".o_card_img");
        imageEl.classList.remove(className);
    }
}
export class RemoveCoverImageAction extends BuilderAction {
    static id = "removeCoverImage";
    static dependencies = ["history", "builderOptions", "remove"];
    apply({ editingElement }) {
        const imageWrapperEl = editingElement.querySelector(".o_card_img_wrapper");
        log.pipeline("RemoveCoverImageAction apply", () => ({
            hadWrapper: !!imageWrapperEl,
        }));
        imageWrapperEl.remove();
        editingElement.classList.remove(...imageRelatedClasses);
        imageRelatedStyles.forEach((prop) => editingElement.style.removeProperty(prop));
    }
}
export class AddCoverImageAction extends BuilderAction {
    static id = "addCoverImage";
    apply({ editingElement }) {
        const endRender = log.perf("AddCoverImageAction render image wrapper");
        const imageWrapper = renderToElement("website.s_card.imageWrapper");
        endRender();
        editingElement.prepend(imageWrapper);
        editingElement.classList.add("o_card_img_top");
    }
}
export class AlignCoverImageAction extends BuilderAction {
    static id = "alignCoverImage";
    apply({ editingElement, params: { mainParam: direction } }) {
        const imgWrapper = editingElement.querySelector(".o_card_img_wrapper");
        log.pipeline("AlignCoverImageAction apply", () => ({ direction }));
        imgWrapper.classList.toggle("o_card_img_adjust_v", direction === "vertical");
        imgWrapper.classList.toggle("o_card_img_adjust_h", direction === "horizontal");
    }
}

registry
    .category("website-plugins")
    .add(CardImageOptionPlugin.id, CardImageOptionPlugin);
