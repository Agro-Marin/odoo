/** @odoo-module native */
import { ImStatus } from "@mail/core/common/im_status";
import { Typing } from "@mail/discuss/typing/common/typing";
import { patch } from "@web/core/utils/patch";
patch(ImStatus, {
    components: { ...ImStatus.components, Typing },
});
