/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
export const helpers = {
    SUPPORTED_M2X_AVATAR_MODELS: ["res.users", "res.partner"],
    /**
     * @param {"res.users"|"res.partner"} resModel
     * @param {number} id
     * @returns {{userId?: number, partnerId?: number}}
     */
    buildOpenChatParams: (resModel, id) => ({
        userId: resModel === "res.users" ? id : undefined,
        partnerId: resModel === "res.partner" ? id : undefined,
    }),
};

/**
 * @param {"res.users"|"res.partner"} resModel
 * @returns {(id: number) => Promise<void>}
 * @throws {Error}
 */
export function useOpenChat(resModel) {
    const store = useService("mail.store");
    if (!helpers.SUPPORTED_M2X_AVATAR_MODELS.includes(resModel)) {
        throw new Error(
            `This widget is only supported on many2one and many2many fields pointing to ${JSON.stringify(
                helpers.SUPPORTED_M2X_AVATAR_MODELS,
            )}`,
        );
    }
    return /** @param {number} id */ async (id) => {
        store.openChat(helpers.buildOpenChatParams(resModel, id));
    };
}
