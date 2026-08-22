/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

import { Plugin } from "../../plugin.js";
import { ImageCrop } from "./image_crop.js";

/**
 * @typedef { Object } ImageCropShared
 * @property { ImageCropPlugin['openCropImage'] } openCropImage
 */

export class ImageCropPlugin extends Plugin {
    static id = "imageCrop";
    static dependencies = ["selection", "history", "imagePostProcess"];
    static shared = ["openCropImage"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "cropImage",
                run: this.openCropImage.bind(this),
                description: _t("Crop image"),
                icon: "fa-crop",
                isAvailable: isHtmlContentSupported,
            },
        ],
        toolbar_items: [
            {
                id: "image_crop",
                commandId: "cropImage",
                groupId: "image_modifiers",
            },
        ],
    };

    getTargetedImage() {
        const targetedNodes = this.dependencies.selection.getTargetedNodes();
        return targetedNodes.find((node) => node.tagName === "IMG");
    }

    async openCropImage(targetedImg, imageCropProps = {}) {
        targetedImg = targetedImg || this.getTargetedImage();
        if (!targetedImg) {
            return;
        }
        return registry.category("main_components").add("ImageCropping", {
            Component: ImageCrop,
            props: {
                media: targetedImg,
                onSave: async (newDataset) => {
                    const updateImageAttributes =
                        await this.dependencies.imagePostProcess.processImage({
                            img: targetedImg,
                            newDataset,
                        });
                    updateImageAttributes();
                    this.dependencies.history.addStep();
                },
                document: this.document,
                ...imageCropProps,
                onClose: () => {
                    registry.category("main_components").remove("ImageCropping");
                    imageCropProps.onClose?.();
                },
            },
        });
    }
}
