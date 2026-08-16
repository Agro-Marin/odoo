/** @odoo-module native */
import { partnerCompareRegistry } from "@mail/core/common/partner_compare";

partnerCompareRegistry.add(
    "discuss.recent-chats",
    /**
     * @param {import("models").ResPartner} p1
     * @param {import("models").ResPartner} p2
     * @param {Object} params
     * @param {import("@web/env").OdooEnv} params.env
     * @param {{recentChatPartnerIds?: number[]}} params.context
     * @returns {number|undefined}
     */
    (p1, p2, { env, context }) => {
        const recentChatPartnerIds =
            context.recentChatPartnerIds ||
            env.services["mail.store"].getRecentChatPartnerIds();
        const recentChatIndex_p1 = recentChatPartnerIds.findIndex(
            (partnerId) => partnerId === p1.id,
        );
        const recentChatIndex_p2 = recentChatPartnerIds.findIndex(
            (partnerId) => partnerId === p2.id,
        );
        if (recentChatIndex_p1 !== -1 && recentChatIndex_p2 === -1) {
            return -1;
        } else if (recentChatIndex_p1 === -1 && recentChatIndex_p2 !== -1) {
            return 1;
        } else if (recentChatIndex_p1 < recentChatIndex_p2) {
            return -1;
        } else if (recentChatIndex_p1 > recentChatIndex_p2) {
            return 1;
        }
    },
    { sequence: 45 },
);

partnerCompareRegistry.add(
    "discuss.members",
    /**
     * @param {import("models").ResPartner} p1
     * @param {import("models").ResPartner} p2
     * @param {Object} params
     * @param {import("models").Thread} [params.thread]
     * @param {{memberPartnerIds: Set<number>}} params.context
     * @returns {number|undefined}
     */
    (p1, p2, { thread, context: { memberPartnerIds } }) => {
        if (thread?.model === "discuss.channel") {
            const isMember1 = memberPartnerIds.has(p1.id);
            const isMember2 = memberPartnerIds.has(p2.id);
            if (isMember1 && !isMember2) {
                return -1;
            }
            if (!isMember1 && isMember2) {
                return 1;
            }
        }
    },
    { sequence: 40 },
);
