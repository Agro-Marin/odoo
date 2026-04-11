/** @odoo-module native */
import { ResPartnerBank } from "./mock_server/mock_models/res_partner_bank.js";
import { mailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";

export const baseIbanModels = {
    ResPartnerBank,
};

export function defineBaseIbanModels() {
    return defineModels({ ...mailModels, ...baseIbanModels });
}
