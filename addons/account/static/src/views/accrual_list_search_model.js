/** @odoo-module native */
import { useEnv, useSubEnv } from "@odoo/owl";
import { SearchModel } from "@web/search/search_model";

/** @param {Record<string, any>} accrualContext */
function provideAccrualContext(accrualContext) {
    useSubEnv({ accrualContext });
}

/** @returns {Record<string, any>} */
export function useAccrualContext() {
    return useEnv().accrualContext;
}

export class AccrualListSearchModel extends SearchModel {
    setup(services) {
        super.setup(services);
        this.accrualContext = {};
        provideAccrualContext(this.accrualContext);
    }

    _getContext() {
        const context = super._getContext();
        Object.assign(context, this.accrualContext);
        return context;
    }
}
