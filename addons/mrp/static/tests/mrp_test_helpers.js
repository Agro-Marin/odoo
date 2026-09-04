import { mailModels } from "@mail/../tests/mail_test_helpers";
import { DocumentsDocument } from "@mrp/../tests/mock_server/mock_models/documents_document";
import { MrpProduction } from "@mrp/../tests/mock_server/mock_models/mrp_production";
import { ResFake } from "@mrp/../tests/mock_server/mock_models/res_fake";
import { UomUom } from "@mrp/../tests/mock_server/mock_models/uom_uom";
import { productModels } from "@product/../tests/product_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";

export function defineMrpModels() {
    return defineModels(mrpModels);
}

export const mrpModels = {
    ...mailModels,
    ...productModels,
    DocumentsDocument,
    MrpProduction,
    ResFake,
    UomUom,
};

export { MrpProduction };
