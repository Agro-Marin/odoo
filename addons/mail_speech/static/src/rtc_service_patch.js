/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { Rtc } from "@mail/discuss/call/common/rtc_service";

patch(Rtc.prototype, {
    /**
     * @param {import("models").Thread} [channel]
     */
    async leaveCall(channel = this.state.channel) {
        await this.env.services["discuss.call_recording"]?.stop();
        return super.leaveCall(channel);
    },
});
