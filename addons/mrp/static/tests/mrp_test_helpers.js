import { mailModels } from "@mail/../tests/mail_test_helpers";
import { DocumentsDocument } from "@mrp/../tests/mock_server/mock_models/documents_document";
import { ResFake } from "@mrp/../tests/mock_server/mock_models/res_fake";
import { defineModels } from "@web/../tests/web_test_helpers";

export function defineMrpModels() {
    return defineModels(mrpModels);
}

export const mrpModels = {
    ...mailModels,
    DocumentsDocument,
    ResFake,
};
