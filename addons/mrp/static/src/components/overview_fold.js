/** @odoo-module native */
import { useEnv } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";

export const FOLD_CHANGED = "fold-changed";
export const FOLD_ALL = "fold-all";

export function useUnfoldedIds() {
    const env = useEnv();
    const unfoldedIds = new Set();
    useBus(env.overviewBus, FOLD_CHANGED, ({ detail }) => {
        const operation = detail.folded ? "delete" : "add";
        detail.ids.forEach((id) => unfoldedIds[operation](id));
    });
    return unfoldedIds;
}
