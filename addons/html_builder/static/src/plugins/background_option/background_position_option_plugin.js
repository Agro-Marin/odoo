/** @odoo-module native */
import { getBgImageURLFromEl } from "@html_builder/utils/utils_css";
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { BackgroundPositionOverlay } from "./background_position_overlay.js";
import { BuilderAction } from "@html_builder/core/builder_action";
import { loadImage } from "@html_editor/utils/image_processing";

// Size given to the image layer when the background repeats as a pattern.
const REPEAT_PATTERN_SIZE = "100px";

const getBgSizeValue = function ({ editingElement, params: { mainParam: styleName } }) {
    // A background can stack several layers -- typically the image on top of a
    // gradient. This option sizes the image, which is always the first one, so
    // split the layers off before reading the width and height out of it.
    const imageLayerSize = editingElement.style.backgroundSize.split(",")[0].trim();
    const bgWidthAndHeight = imageLayerSize.split(/\s+/g);
    const value = styleName === "width" ? bgWidthAndHeight[0] : bgWidthAndHeight[1] || "";
    return value === "auto" ? "" : value;
};

class BackgroundPositionOptionPlugin extends Plugin {
    static id = "backgroundPositionOption";
    static dependencies = ["overlay", "overlayButtons"];
    /** @type {import("plugins").BuilderResources} */
    resources = {
        builder_actions: {
            BackgroundTypeAction,
            SetBackgroundSizeAction,
            BackgroundPositionOverlayAction,
        },
    };
}

export class BackgroundTypeAction extends BuilderAction {
    static id = "backgroundType";
    apply({ editingElement, value }) {
        editingElement.classList.toggle("o_bg_img_opt_repeat", value === "repeat-pattern");
        editingElement.style.setProperty("background-position", "");
        editingElement.style.setProperty(
            "background-size",
            value !== "repeat-pattern" ? "" : `${REPEAT_PATTERN_SIZE}, cover`
        );
    }
    isApplied({ editingElement, value }) {
        // `background-repeat` computes to one entry per background layer, so an
        // element carrying a gradient behind its image reads "repeat, repeat".
        // Comparing the whole string against a single keyword would report
        // "Cover" on any multi-layer background, whatever is applied.
        const isRepeating = getComputedStyle(editingElement)
            .backgroundRepeat.split(",")
            .every((repeat) => repeat.trim() === "repeat");
        return value === "repeat-pattern" ? isRepeating : !isRepeating;
    }
}

export class SetBackgroundSizeAction extends BuilderAction {
    static id = "setBackgroundSize";
    getValue(context) {
        return getBgSizeValue(context);
    }
    apply({ editingElement, params: { mainParam: styleName }, value }) {
        const otherParam = styleName === "width" ? "height" : "width";
        let otherBgSize = getBgSizeValue({
            editingElement: editingElement,
            params: { mainParam: otherParam },
        });
        let bgSize;
        value ||= "auto";
        if (styleName === "width") {
            otherBgSize = otherBgSize === "" ? "" : ` ${otherBgSize}`;
            bgSize = `${value}${otherBgSize}`;
        } else {
            otherBgSize ||= "auto";
            bgSize = `${otherBgSize} ${value}`;
        }
        // Keep the layer behind the image covering: only the image is resized.
        editingElement.style.setProperty("background-size", `${bgSize}, cover`);
    }
}

export class BackgroundPositionOverlayAction extends BuilderAction {
    static id = "backgroundPositionOverlay";
    static dependencies = ["overlayButtons", "history"];
    setup() {
        this.withLoadingEffect = false;
    }
    async load({ editingElement }) {
        const imgEl = await loadImage(getBgImageURLFromEl(editingElement));
        return new Promise((resolve) => {
            // Hide the builder overlay buttons when the user changes
            // the background position.
            this.dependencies.overlayButtons.hideOverlayButtonsUi();
            let appliedBgPosition = "";
            const onRemove = () => {
                this.dependencies.overlayButtons.showOverlayButtonsUi();
                resolve(appliedBgPosition);
            };
            const removeOverlay = this.services.overlay.add(
                BackgroundPositionOverlay,
                {
                    editingElement: editingElement,
                    mockEditingElOnImg: imgEl,
                    applyPosition: (bgPosition) => {
                        appliedBgPosition = bgPosition;
                        removeOverlay();
                    },
                    discardPosition: () => removeOverlay(),
                    editable: this.editable,
                    history: {
                        makeSavePoint: this.dependencies.history.makeSavePoint,
                    },
                },
                { onRemove }
            );
        });
    }
    apply({ editingElement, loadResult: bgPosition }) {
        if (bgPosition) {
            editingElement.style.backgroundPosition = bgPosition;
        }
    }
}

registry
    .category("builder-plugins")
    .add(BackgroundPositionOptionPlugin.id, BackgroundPositionOptionPlugin);
