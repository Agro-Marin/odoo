import {
    getMockEnv,
    makeMockEnv,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { session } from "@web/session";
import { getDocumentsModel } from "./data.js";

/**
 * @param {{ serverData?: Record<string, any[]> }} [params]
 */
export async function makeDocumentsMockEnv(params) {
    // The fixture mocks document.sharing and document.operation, so it
    // stands for an install that has document_enterprise unless a test
    // says otherwise.
    patchWithCleanup(session, {
        document_enterprise_actions: params?.enterpriseActions ?? true,
    });
    if (params?.serverData) {
        for (const [modelName, records] of Object.entries(params.serverData)) {
            if (!records?.length) {
                continue;
            }
            const PyModel = getDocumentsModel(modelName);
            if (!PyModel) {
                throw new Error(`Model ${modelName} not found inside DocumentsModels`);
            }
            PyModel._records = records;
        }
    }
    const env = getMockEnv() || (await makeMockEnv());
    env.services["document.document"].store.odoobot = {
        userId: serverState.odoobotId,
    };
    return env;
}
