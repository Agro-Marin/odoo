/** @odoo-module native */
import { loadAssets } from "@im_livechat/embed/common/boot_helpers";
import { mailPopoutService } from "@mail/core/common/mail_popout_service";
import { patch } from "@web/core/utils/patch";

const popoutPatch = {
    async addAssets(window) {
        await super.addAssets(...arguments);
        await new Promise((resolve) => {
            if (window.document.readyState === "complete") {
                resolve();
            } else {
                window.addEventListener("load", resolve, { once: true });
            }
        });
        await window.document.fonts.ready;
        await loadAssets(window.document.head);
    },
};
patch(mailPopoutService, popoutPatch);
