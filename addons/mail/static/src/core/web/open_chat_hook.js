// @ts-check
/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("mail.store");
export const helpers = {
    SUPPORTED_M2X_AVATAR_MODELS: ["res.users", "res.partner"],
    /**
     * @param {"res.users"|"res.partner"} resModel
     * @param {number} id
     * @returns {{userId?: number, partnerId?: number}}
     */
    prepareOpenChatParams: (resModel, id) => ({
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
        log.logic("useOpenChat", () => ({ resModel, id }));
        store.openChat(helpers.prepareOpenChatParams(resModel, id));
    };
}
