/** @odoo-module native */
import { DiscussCoreCommon } from "@mail/discuss/core/common/discuss_core_common_service";
import { patch } from "@web/core/utils/patch";
/** @type {DiscussCoreCommon} */
const discussCoreCommon = {
    /** @param {...any} args */
    async _handleNotificationNewMessage(...args) {
        await this.store.channels.fetch();
        return super._handleNotificationNewMessage(...args);
    },
};

patch(DiscussCoreCommon.prototype, discussCoreCommon);
