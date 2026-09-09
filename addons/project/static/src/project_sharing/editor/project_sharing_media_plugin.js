/** @odoo-module native */
import { ImageCropPlugin } from "@html_editor/main/media/image_crop_plugin";
import { ImageSavePlugin } from "@html_editor/main/media/image_save_plugin";
import { MediaPlugin } from "@html_editor/main/media/media_plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";

export class ProjectSharingMediaPlugin extends MediaPlugin {
    resources = {
        ...this.resources,
        toolbar_items: this.resources.toolbar_items.filter(
            (item) => item.id !== "replace_image",
        ),
    };
}

export class ProjectSharingImageSavePlugin extends ImageSavePlugin {
    async createAttachment({ el, imageData, resId }) {
        const formData = new FormData();
        for (const [key, value] of Object.entries({
            name: el.dataset.fileName || "",
            data: imageData,
            res_id: resId,
            csrf_token: odoo.csrf_token,
        })) {
            formData.append(key, value);
        }
        const response = await browser.fetch("/project_sharing/attachment/add_image", {
            method: "POST",
            body: formData,
        });
        let attachment = null;
        try {
            attachment = await response.json();
        } catch {
        }
        if (!response.ok || !attachment || attachment.error) {
            this.services.notification.add(
                attachment?.error ||
                    _t("The image could not be uploaded (HTTP %s).", response.status),
                { type: "danger" },
            );
            el.remove();
            return;
        }
        attachment.image_src = "/web/image/" + attachment.id + "-" + attachment.name;
        return attachment;
    }
}

function replacePlugin(oldPlugin, newPlugin) {
    const index = MAIN_PLUGINS.indexOf(oldPlugin);
    if (index !== -1) {
        MAIN_PLUGINS.splice(index, 1);
    }
    if (newPlugin) {
        MAIN_PLUGINS.push(newPlugin);
    }
}

replacePlugin(MediaPlugin, ProjectSharingMediaPlugin);
replacePlugin(ImageSavePlugin, ProjectSharingImageSavePlugin);
replacePlugin(ImageCropPlugin, null);
