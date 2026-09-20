/** @odoo-module native */
import { reactive, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class AuditBalanceListChatterService {
    constructor() {
        this.chatterState = reactive({ res_id: undefined, date_to: undefined });
    }

    closeChatter() {
        this.chatterState.res_id = undefined;
    }

    openChatter(resId) {
        this.chatterState.res_id = resId;
    }
}

const auditBalanceListChatterService = {
    start() {
        return new AuditBalanceListChatterService();
    },
};

registry
    .category("services")
    .add("auditBalanceListChatterService", auditBalanceListChatterService);

export function useAuditBalanceListChatterService() {
    return useState(useService("auditBalanceListChatterService"));
}
