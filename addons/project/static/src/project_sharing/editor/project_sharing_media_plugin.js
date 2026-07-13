/** @odoo-module native */
import { ImageCropPlugin } from "@html_editor/main/media/image_crop_plugin";
import { ImageSavePlugin } from "@html_editor/main/media/image_save_plugin";
import { MediaPlugin } from "@html_editor/main/media/media_plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";

export class ProjectSharingMediaPlugin extends MediaPlugin {
    resources = {
        ...this.resources,
        toolbar_items: this.resources.toolbar_items.filter(
            item => item.id !== "replace_image"
        ),
    }
}

export class ProjectSharingImageSavePlugin extends ImageSavePlugin {
    async createAttachment({ el, imageData, resId }) {
        const response = JSON.parse(
            await this.services.http.post(
                "/project_sharing/attachment/add_image",
                {
                    name: el.dataset.fileName || "",
                    data: imageData,
                    res_id: resId,
                    access_token: "",
                    csrf_token: odoo.csrf_token,
                },
                "text"
            )
        );
        if (response.error) {
            this.services.notification.add(response.error, { type: "danger" });
            el.remove();
            // Abort: the base saveB64Image treats a falsy return as "no
            // attachment". Without this the error object falls through and is
            // returned as a bogus attachment (src="/web/image/undefined-...").
            return;
        }
        const attachment = response;
        attachment.image_src = "/web/image/" + attachment.id + "-" + attachment.name;
        return attachment;
    }
}

// Swap the base media plugins for the project-sharing variants. Guard each
// indexOf: a bare splice(indexOf(...), 1) would remove the LAST element when
// the target plugin is absent (indexOf → -1 → splice(-1, 1)).
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
