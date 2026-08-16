/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { patch } from "@web/core/utils/patch";
patch(DiscussClientAction.prototype, {
    async restoreDiscussThread() {
        await this.store.channels.fetch();
        return super.restoreDiscussThread(...arguments);
    },
    /**
     * @param {string|number} rawActiveId
     * @returns {[string, number]|undefined}
     */
    parseActiveId(rawActiveId) {
        if (typeof rawActiveId === "number") {
            return ["discuss.channel", rawActiveId];
        }
        const parsedActiveId = super.parseActiveId(rawActiveId);
        if (!parsedActiveId) {
            return parsedActiveId;
        }
        const [model, id] = parsedActiveId;
        if (model === "mail.channel") {
            return ["discuss.channel", id];
        }
        return [model, id];
    },
});
