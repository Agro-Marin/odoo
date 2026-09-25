/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { onWillStart } from "@odoo/owl";
import { usePortalContext } from "@portal/chatter/core/portal_context";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    setup() {
        super.setup();
        this.portalContext = usePortalContext();
        onWillStart(() => {
            if (this.thread && !this.thread.id) {
                this.state.active = false;
            }
        });
    },

    get extraData() {
        const extraData = super.extraData;
        if (this.portalContext.projectSharingId) {
            extraData.project_sharing_id = this.portalContext.projectSharingId;
        }
        return extraData;
    },

    get isSendButtonDisabled() {
        if (this.thread && !this.thread.id) {
            return true;
        }
        return super.isSendButtonDisabled;
    },

    get allowUpload() {
        if (this.thread && !this.thread.id) {
            return false;
        }
        return super.allowUpload;
    },

    get shouldHideFromMessageListOnDelete() {
        return true;
    },
});
