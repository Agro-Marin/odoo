import { registry } from "@web/core/registry";
import { createRelatedModels } from "@point_of_sale/app/models/related_models";
import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";
import { MockServer } from "@web/../tests/web_test_helpers";

export const getModelDefinitions = () => {
    const session = MockServer.current._models["pos.session"];
    const params = session.load_data_params();
    return Object.entries(params).reduce((acc, [modelName, params]) => {
        acc[modelName] = params.relations;
        return acc;
    }, {});
};

let generatedModels = null;
// The instance is cached so repeated calls within a single test share it, but the
// cache must not leak across tests (records would accumulate on a shared instance).
// Each test spins up a fresh MockServer via makeMockServer(), so key the cache on
// the current server (and on useModelClass) and rebuild when either changes.
let generatedModelsKey = null;

export const getRelatedModelsInstance = (useModelClass = true) => {
    const cacheKey = { server: MockServer.current, useModelClass };
    if (
        generatedModels &&
        generatedModelsKey &&
        generatedModelsKey.server === cacheKey.server &&
        generatedModelsKey.useModelClass === cacheKey.useModelClass
    ) {
        return generatedModels;
    }

    const options = new DataServiceOptions();
    const relations = getModelDefinitions();
    const modelClasses = {};

    if (useModelClass) {
        for (const posModel of registry.category("pos_available_models").getAll()) {
            const pythonModel = posModel.pythonModel;
            const extraFields = posModel.extraFields || {};

            modelClasses[pythonModel] = posModel;
            relations[pythonModel] = {
                ...relations[pythonModel],
                ...extraFields,
            };
        }
    }

    const models = createRelatedModels(relations, useModelClass ? modelClasses : {}, options);
    generatedModels = models.models;
    generatedModelsKey = cacheKey;
    return models.models;
};
