/** @odoo-module native */
import { rpc, RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { checkFileSize } from "@web/core/utils/files";
import { getDataURLFromFile } from "@web/core/utils/urls";
import { Interaction } from "@web/public/interaction";

export class PortalProfileEditor extends Interaction {
    static selector = ".o_portal_profile_card";
    dynamicContent = {
        ".o_portal_profile_pic_upload": {
            "t-on-change": this.locked(this.uploadPicture, true),
        },
        ".o_portal_profile_pic_edit": {
            "t-on-click.prevent": this.pickFile,
        },
        ".o_portal_profile_pic_clear": {
            "t-on-click.prevent": this.locked(this.clearPicture, true),
        },
    };

    setup() {
        this.fileInputEl = this.el.querySelector(".o_portal_profile_pic_upload");
    }

    pickFile() {
        this.fileInputEl.click();
    }

    async uploadPicture() {
        const file = this.fileInputEl.files[0];
        // Let the same file be picked again after a failed upload.
        this.fileInputEl.value = "";
        if (!file || !checkFileSize(file.size, this.services.notification)) {
            return;
        }
        const dataUrl = await this.waitFor(getDataURLFromFile(file));
        await this.savePicture(dataUrl.split(",")[1]);
    }

    async clearPicture() {
        await this.savePicture(false);
    }

    /**
     * @param {string|false} image_1920
     */
    async savePicture(image_1920) {
        try {
            await this.waitFor(rpc("/my/profile/save", { image_1920 }));
        } catch (error) {
            if (error instanceof RPCError) {
                this.services.notification.add(
                    error.data?.message ||
                        _t("The profile picture could not be saved."),
                    { type: "danger" },
                );
                return;
            }
            throw error;
        }
        // The same avatar is painted by the navbar dropdown and the offcanvas,
        // so refresh the document rather than patching this one <img>.
        location.reload();
    }
}

registry
    .category("public.interactions")
    .add("portal.portal_profile_editor", PortalProfileEditor);
