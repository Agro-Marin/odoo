import { mailModels } from "@mail/../tests/mail_test_helpers";
import { ProductDocument } from "@mrp/../tests/mock_server/mock_models/product_document";
import { ResFake } from "@mrp/../tests/mock_server/mock_models/res_fake";
import { defineModels } from "@web/../tests/web_test_helpers";

export function defineMrpModels() {
    return defineModels(mrpModels);
}

export const mrpModels = {
    ...mailModels,
    ProductDocument,
    ResFake,
};
