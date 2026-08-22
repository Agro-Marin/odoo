import { defineModels } from "@web/../tests/web_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { DocumentsModels } from "@documents/../tests/helpers/data";

export const documentsModels = DocumentsModels;

export function defineDocumentsModels() {
    registerMailMockRoutes();
    return defineModels(documentsModels);
}
