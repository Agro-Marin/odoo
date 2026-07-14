/** @odoo-module native */
import { ImageCropPlugin } from "@html_editor/main/media/image_crop_plugin";
import { ImageSavePlugin } from "@html_editor/main/media/image_save_plugin";
import { MediaPlugin } from "@html_editor/main/media/media_plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";

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
        // Raw fetch instead of services.http: the route answers its rejection
        // payload (e.g. disallowed mimetype) with HTTP 400, and http.post
        // throws an opaque NetworkError on any non-ok status — the JSON error
        // body would never reach us.
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
            // Non-JSON body (e.g. a proxy error page): fall through to the
            // generic error handling below.
        }
        if (!response.ok || !attachment || attachment.error) {
            this.services.notification.add(
                attachment?.error ||
                    _t("The image could not be uploaded (HTTP %s).", response.status),
                { type: "danger" }
            );
            el.remove();
            // Abort: the base saveB64Image treats a falsy return as "no
            // attachment". Without this the error object falls through and is
            // returned as a bogus attachment (src="/web/image/undefined-...").
            return;
        }
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
